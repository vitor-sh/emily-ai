using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Net.Http;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Modding;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace EmilyCompanion
{
    internal sealed class EmilyBridgeClient : IDisposable
    {
        private const string BaseUrl = "http://127.0.0.1:57124/v1/hollow-knight";
        // O primeiro /models do OmniRoute pode pagar aquecimento de alguns
        // segundos após login/restart. Oito segundos evitam falso offline sem
        // afetar o polling normal, que continua respondendo localmente rápido.
        private readonly HttpClient _http = new HttpClient { Timeout = TimeSpan.FromSeconds(8) };
        private readonly HttpClient _audioHttp = new HttpClient { Timeout = TimeSpan.FromSeconds(90) };
        private readonly ConcurrentQueue<Action> _main = new ConcurrentQueue<Action>();
        private readonly ConcurrentQueue<object> _events = new ConcurrentQueue<object>();
        private readonly ConcurrentQueue<object> _priorityEvents = new ConcurrentQueue<object>();
        private object _deferredActivationEvent;
        private const int MaxQueuedEvents = 80;
        private const int MaxPriorityEvents = 40;
        private static readonly HashSet<string> PriorityEventTypes = new HashSet<string>
        {
            "boas_vindas", "boss_derrotado", "magia_adquirida", "amuleto_adquirido",
            "estacao_desbloqueada", "item_importante_adquirido",
            "habilidade_adquirida", "banco_descoberto", "charm_adquirido",
            "banco", "npc_dialogo", "boss_encontrado", "boss_iniciado", "boss_luta",
            "boss_fase", "morte",
        };
        private readonly string _tokenPath;
        private string _token = "";
        private string _session = "";
        private string _campaign = "";
        private readonly string _runId = Guid.NewGuid().ToString("N").Substring(0, 12);
        private long _eventId;
        private int _lastSequence;
        private volatile bool _busy;
        private volatile bool _online;
        private volatile bool _enabled = true;
        private volatile bool _voice = true;
        private volatile int _volume = 90;
        private volatile string _speechMode = "normal";
        private volatile string _model = "";
        private bool _configurationDirty;
        private int _configurationRevision;
        private int _generation;
        private float _nextPoll;
        public bool Online => _online;
        public Action<EmilySpeechItem> OnSpeech;
        public Action<int, byte[]> OnVoice;
        public Action<int, EmilyPcmStream> OnVoiceStream;

        public EmilyBridgeClient()
        {
            var dir = Path.GetDirectoryName(typeof(EmilyCompanionMod).Assembly.Location);
            _tokenPath = Path.Combine(dir ?? "", "emily-hk-token.txt");
            TryLoadToken();
        }

        public void Configure(EmilyGlobalSettings settings, bool active)
        {
            if (settings == null) return;
            var wasEnabled = _enabled;
            _enabled = settings.IntegracaoIa && active;
            if (_voice != settings.Voz) { _configurationDirty = true; _configurationRevision++; }
            _voice = settings.Voz;
            _volume = Math.Max(0, Math.Min(200, settings.Volume));
            var mode = settings.ModoFala ?? "normal";
            var model = settings.Modelo ?? "";
            if (_speechMode != mode || _model != model)
            {
                _configurationDirty = true;
                _configurationRevision++;
            }
            _speechMode = mode;
            _model = model;
            if (wasEnabled != _enabled)
                Interlocked.Increment(ref _generation);
            if (!wasEnabled && _enabled) _nextPoll = 0f;
            if (!_enabled && wasEnabled)
            {
                Action pendingAction;
                object pendingEvent;
                while (_main.TryDequeue(out pendingAction)) { }
                while (_events.TryDequeue(out pendingEvent)) { }
                while (_priorityEvents.TryDequeue(out pendingEvent)) { }
                _session = "";
                _online = false;
            }
        }

        private void TryLoadToken()
        {
            if (!File.Exists(_tokenPath)) return;
            var loaded = File.ReadAllText(_tokenPath).Trim();
            if (string.IsNullOrEmpty(loaded) || loaded == _token) return;
            _token = loaded;
            _session = "";
            _lastSequence = 0;
            _http.DefaultRequestHeaders.Remove("Authorization");
            _http.DefaultRequestHeaders.TryAddWithoutValidation("Authorization", "Bearer " + _token);
            _audioHttp.DefaultRequestHeaders.Remove("Authorization");
            _audioHttp.DefaultRequestHeaders.TryAddWithoutValidation("Authorization", "Bearer " + _token);
        }

        public void Enqueue(string type, string sceneId, object data)
        {
            var payload = new {
                id = "mod-" + _runId + "-" + (++_eventId), cena_id = sceneId ?? "", tipo = type,
                criado_em = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0,
                dados = data ?? new { }
            };
            if (!_enabled && type == "charm_adquirido")
            {
                _deferredActivationEvent = payload;
                return;
            }
            if (!_enabled) return;
            var target = PriorityEventTypes.Contains(type) ? _priorityEvents : _events;
            var limit = PriorityEventTypes.Contains(type) ? MaxPriorityEvents : MaxQueuedEvents;
            object discarded;
            while (target.Count >= limit && target.TryDequeue(out discarded)) { }
            target.Enqueue(payload);
            // Eventos recém-observados não precisam esperar o próximo ciclo do
            // polling. A fila, retry e confirmação continuam iguais; só acorda
            // o transporte local na próxima atualização do jogo.
            _nextPoll = 0f;
        }

        public void Update(string campaignId, string sceneId)
        {
            if (!_enabled)
            {
                _online = false;
                return;
            }
            BindCampaign(campaignId);
            if (_deferredActivationEvent != null)
            {
                _priorityEvents.Enqueue(_deferredActivationEvent);
                _deferredActivationEvent = null;
                _nextPoll = 0f;
            }
            Action action;
            while (_main.TryDequeue(out action))
            {
                try { action(); } catch (Exception e) { Modding.Logger.LogError(e); }
            }
            if (_busy || Time.unscaledTime < _nextPoll) return;
            _nextPoll = Time.unscaledTime + .35f;
            if (string.IsNullOrEmpty(_token) || !Online) TryLoadToken();
            _busy = true;
            var generation = _generation;
            Task.Run(async () =>
            {
                try
                {
                    if (string.IsNullOrEmpty(_token)) throw new InvalidOperationException("token ausente");
                    if (string.IsNullOrEmpty(_session) && !await CreateSession(campaignId, generation)) return;
                    if (!_enabled || generation != _generation) return;
                    await FlushEvents(generation);
                    if (!_enabled || generation != _generation) return;
                    await PollCommands(sceneId, generation);
                    if (_enabled && generation == _generation) _online = true;
                }
                catch (Exception e)
                {
                    if (_enabled && generation == _generation)
                    {
                        _online = false;
                        if (e is HttpRequestException) _session = "";
                    }
                }
                finally { _busy = false; }
            });
        }

        public void BindCampaign(string campaignId)
        {
            campaignId = campaignId ?? "save-desconhecido";
            if (_campaign != campaignId)
            {
                _campaign = campaignId;
                _session = "";
                _lastSequence = 0;
                _online = false;
                Interlocked.Increment(ref _generation);
                object oldEvent;
                Action oldAction;
                while (_events.TryDequeue(out oldEvent)) { }
                while (_priorityEvents.TryDequeue(out oldEvent)) { }
                while (_main.TryDequeue(out oldAction)) { }
            }
        }

        private async Task<bool> CreateSession(string campaignId, int generation)
        {
            var revision = _configurationRevision;
            var response = await Post("/sessao", new {
                campanha_id = campaignId, versao_mod = EmilyCompanionMod.Version,
                configuracao = CurrentConfiguration()
            });
            if (!_enabled || generation != _generation) return false;
            _session = (string)response["sessao_id"];
            var applied = (string)response["configuracao"]?["modelo"] ?? "";
            if (applied != _model)
                Modding.Logger.LogWarn("Emily Companion: modelo solicitado não disponível na ponte; usando o padrão do gateway.");
            _lastSequence = 0;
            if (revision == _configurationRevision) _configurationDirty = false;
            return !string.IsNullOrEmpty(_session);
        }

        public void ResetForSave()
        {
            Interlocked.Increment(ref _generation);
            _session = "";
            _campaign = "";
            _lastSequence = 0;
            _online = false;
            _nextPoll = 0f;
            _deferredActivationEvent = null;
            object value;
            Action action;
            while (_events.TryDequeue(out value)) { }
            while (_priorityEvents.TryDequeue(out value)) { }
            while (_main.TryDequeue(out action)) { }
        }

        private async Task FlushEvents(int generation)
        {
            if (_events.IsEmpty && _priorityEvents.IsEmpty && !_configurationDirty) return;
            var batch = new List<object>();
            var priorityBatch = new List<object>();
            var normalBatch = new List<object>();
            object item;
            while (batch.Count < 30 && _priorityEvents.TryDequeue(out item))
            {
                priorityBatch.Add(item);
                batch.Add(item);
            }
            while (batch.Count < 30 && _events.TryDequeue(out item))
            {
                normalBatch.Add(item);
                batch.Add(item);
            }
            var revision = _configurationRevision;
            try { var response = await Post("/eventos", new {
                sessao_id = _session, configuracao = CurrentConfiguration(), eventos = batch
            });
                if (generation == _generation)
                {
                    if (revision == _configurationRevision) _configurationDirty = false;
                    var applied = (string)response["configuracao"]?["modelo"] ?? "";
                    if (applied != _model)
                        Modding.Logger.LogWarn("Emily Companion: modelo solicitado não disponível na ponte; usando o padrão do gateway.");
                }
            }
            catch
            {
                if (_enabled && generation == _generation)
                {
                    foreach (var value in priorityBatch) _priorityEvents.Enqueue(value);
                    foreach (var value in normalBatch) _events.Enqueue(value);
                }
                throw;
            }
        }

        private async Task PollCommands(string sceneId, int generation)
        {
            var session = _session;
            var url = BaseUrl + "/comandos?sessao_id=" + Uri.EscapeDataString(session) +
                      "&desde=" + _lastSequence + "&cena_id=" + Uri.EscapeDataString(sceneId ?? "");
            var raw = await _http.GetStringAsync(url);
            if (!_enabled || generation != _generation || session != _session) return;
            var root = JObject.Parse(raw);
            foreach (var command in (JArray)root["comandos"] ?? new JArray())
            {
                if (!_enabled || generation != _generation || session != _session) return;
                var sequence = (int)command["sequencia"];
                _lastSequence = Math.Max(_lastSequence, sequence);
                var type = (string)command["tipo"];
                var data = (JObject)command["dados"] ?? new JObject();
                if (type == "fala")
                {
                    var item = new EmilySpeechItem {
                        Sequence = sequence,
                        Text = (string)data["texto"] ?? "",
                        Emotion = (string)data["emocao"] ?? "neutra",
                        Suggested = (string)data["acao"] ?? "nenhuma",
                        Zone = (string)data["zona"] ?? "",
                        ValidateZone = (bool?)data["validar_zona"] ?? false,
                        Persistent = (bool?)data["persistente"] ?? false,
                        VoiceExpected = (bool?)data["voz_prevista"] ?? _voice,
                    };
                    // Compatibilidade com falas antigas que traziam áudio embutido.
                    var inlineAudioId = (string)data["audio_id"] ?? "";
                    if (_voice && !string.IsNullOrEmpty(inlineAudioId))
                        try
                        {
                            item.Wav = await _http.GetByteArrayAsync(
                                BaseUrl + "/audio/" + Uri.EscapeDataString(inlineAudioId));
                            item.VoiceResolved = item.Wav != null && item.Wav.Length > 44;
                        }
                        catch
                        {
                            item.Wav = null;
                            item.VoiceResolved = true;
                        }
                    if (!item.VoiceExpected) item.VoiceResolved = true;
                    if (!_enabled || generation != _generation) continue;
                    _main.Enqueue(() =>
                    {
                        if (_enabled && generation == _generation) OnSpeech?.Invoke(item);
                    });
                }
                else if (type == "audio")
                {
                    var speechSequence = (int?)data["fala_sequencia"] ?? 0;
                    var audioId = (string)data["audio_id"] ?? "";
                    var streaming = (bool?)data["streaming"] ?? false;
                    if (_voice && streaming && !string.IsNullOrEmpty(audioId))
                    {
                        var sampleRate = (int?)data["sample_rate"] ?? 44100;
                        var channels = (int?)data["channels"] ?? 1;
                        _ = ReceivePcmStream(
                            speechSequence, audioId, sampleRate, channels, generation);
                        continue;
                    }
                    byte[] wav = null;
                    if (_voice && !string.IsNullOrEmpty(audioId))
                        try { wav = await _http.GetByteArrayAsync(BaseUrl + "/audio/" + Uri.EscapeDataString(audioId)); }
                        catch { wav = null; }
                    if (!_enabled || generation != _generation) continue;
                    var pronto = wav;
                    _main.Enqueue(() =>
                    {
                        if (_enabled && generation == _generation) OnVoice?.Invoke(speechSequence, pronto);
                    });
                }
            }
            if (_lastSequence > 0 && generation == _generation && session == _session)
                await Post("/confirmar", new { sessao_id = session, sequencia = _lastSequence });
        }

        private async Task ReceivePcmStream(int speechSequence, string audioId,
                                            int sampleRate, int channels,
                                            int generation)
        {
            var pcm = new EmilyPcmStream(sampleRate, channels);
            _main.Enqueue(() =>
            {
                if (_enabled && generation == _generation)
                    OnVoiceStream?.Invoke(speechSequence, pcm);
                else
                    pcm.Complete();
            });
            try
            {
                var url = BaseUrl + "/audio-stream/" + Uri.EscapeDataString(audioId);
                using (var response = await _audioHttp.GetAsync(
                    url, HttpCompletionOption.ResponseHeadersRead))
                {
                    response.EnsureSuccessStatusCode();
                    using (var stream = await response.Content.ReadAsStreamAsync())
                    {
                        var buffer = new byte[8192];
                        while (_enabled && generation == _generation)
                        {
                            var read = await stream.ReadAsync(buffer, 0, buffer.Length);
                            if (read <= 0) break;
                            pcm.Append(buffer, read);
                        }
                    }
                }
            }
            catch (Exception e)
            {
                Modding.Logger.LogWarn("Stream de voz da Emily interrompido: " + e.Message);
            }
            finally
            {
                pcm.Complete();
            }
            if (!pcm.HasData && _enabled && generation == _generation)
            {
                byte[] wav = null;
                try
                {
                    wav = await _audioHttp.GetByteArrayAsync(
                        BaseUrl + "/audio/" + Uri.EscapeDataString(audioId));
                }
                catch { wav = null; }
                var fallback = wav;
                _main.Enqueue(() =>
                {
                    if (_enabled && generation == _generation)
                        OnVoice?.Invoke(speechSequence, fallback);
                });
            }
        }

        private async Task<JObject> Post(string route, object body)
        {
            var content = new StringContent(JsonConvert.SerializeObject(body), Encoding.UTF8, "application/json");
            var response = await _http.PostAsync(BaseUrl + route, content);
            response.EnsureSuccessStatusCode();
            return JObject.Parse(await response.Content.ReadAsStringAsync());
        }

        private object CurrentConfiguration() => new {
            modo_fala = _speechMode,
            modelo = _model,
            voz = _voice,
            volume = _volume / 100f
        };

        public void Dispose()
        {
            _http.Dispose();
            _audioHttp.Dispose();
        }
    }
}