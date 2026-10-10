using System;
using System.Collections.Generic;
using Modding;
using SFCore;
using UnityEngine;

namespace EmilyCompanion
{
    public sealed class EmilyCompanionMod : Mod, ILocalSettings<EmilySaveSettings>,
        IGlobalSettings<EmilyGlobalSettings>, IMenuMod, ITogglableMod
    {
        public const string Version = "0.5.4";
        public static EmilyCompanionMod Instance { get; private set; }
        private EmilySaveSettings _save = new EmilySaveSettings();
        private EmilyGlobalSettings _settings = new EmilyGlobalSettings();
        private EmilyCharm _charm;
        private EmilyFairyController _fairy;
        private EmilyPickup _pickup;
        private EmilyHud _hud;
        private EmilyBridgeClient _bridge;
        private EmilyProgressTracker _progress;
        private EmilyDialogueTracker _dialogue;
        private EmilyBossTracker _boss;
        private EmilyCombatContext _combat;
        private EmilyVoicePlayer _voicePlayer;
        private readonly EmilyAudioDucker _audioDucker = new EmilyAudioDucker();
        private readonly Queue<EmilySpeechItem> _speechQueue = new Queue<EmilySpeechItem>();
        private readonly Dictionary<int, EmilySpeechItem> _speechBySequence =
            new Dictionary<int, EmilySpeechItem>();
        private const int MaxQueuedSpeech = 8;
        private const float VoiceWaitTimeout = 18f;
        // A fala espera o jogo liberar (fim de cutscene, diálogo, transição),
        // mas não para sempre: linha velha perde o sentido.
        // 0.5.0: 25s era curto demais — a intro de chefe com title card passa
        // disso e a fala era descartada antes de o jogador retomar o controle.
        private const float SpeechHoldLimit = 60f;
        private const float PersistentSpeechHoldLimit = 180f;
        private EmilySpeechItem _currentSpeech;
        private float _voiceWaitUntil;
        private float _speechEndsAt;
        private float _holdStartedAt;
        private bool _speechStarted;
        private bool _wasActive;
        private string _sceneId = "";
        private int _sceneSequence;
        private float _nextState;
        private float _nextProgressCheck;
        private float _nextChatterAt;
        private float _sessionStartedAt;
        private float _lastTrackingAt;
        private float _activeSinceState;
        private float _lastMovementAt;
        private float _distanceThisSession;
        private Vector3 _lastHeroPosition;
        private bool _trackingReady;
        private bool _lastBench;
        private int _healthBeforeDamage = -1;
        private int _resolvedIncomingDamage;
        private int _pendingHazardType;
        private float _pendingDamageAt;
        private readonly Dictionary<string, float> _lastAutomaticPowerEvent =
            new Dictionary<string, float>();
        private static readonly HashSet<string> ImportantEvents = new HashSet<string>
        {
            "boss_derrotado", "magia_adquirida", "amuleto_adquirido",
            "estacao_desbloqueada", "item_importante_adquirido",
            "habilidade_adquirida", "banco_descoberto", "charm_adquirido",
        };
        private string _announcedCampaign = "";
        // Última zona vista, para `area_nova` valer como REGIÃO e não como
        // troca de sala. A primeira cena de cada sessão apenas registra a zona
        // (a saudação cobre esse momento) sem gerar comentário de área.
        private string _zonaVista = "";
        private bool _zonaInicialPendente = true;
        // Saudação de abertura. Só é zerada em jogo novo/carregamento de save,
        // então reequipar o vínculo no meio da partida não faz ela cumprimentar
        // de novo.
        private string _greetedCampaign = "";
        private bool _initialized;
        public bool Active => _save.EncontrouEmily && _charm != null && _charm.IsEquipped;
        internal object CombatSnapshot() => _combat?.Snapshot();
        internal bool AutomaticAttacksEnabled => _settings.AtaquesAutomaticos;
        internal bool OffensivePowersEnabled => _settings.PoderesOfensivos;
        internal bool SupportPowersEnabled => _settings.PoderesSuporte;

        public EmilyCompanionMod() : base("EmilyCompanion") => Instance = this;
        public override string GetVersion() => Version;

        public override void Initialize()
        {
            if (_initialized) return;
            _initialized = true;
            _charm = new EmilyCharm();
            _hud = new EmilyHud();
            _bridge = new EmilyBridgeClient();
            _progress = new EmilyProgressTracker(this);
            _dialogue = new EmilyDialogueTracker(this);
            _boss = new EmilyBossTracker(this);
            _combat = new EmilyCombatContext(() => Active);
            _voicePlayer = new EmilyVoicePlayer();
            _bridge.Configure(_settings, false);
            _bridge.OnSpeech = OnSpeech;
            _bridge.OnVoice = OnVoice;
            _bridge.OnVoiceStream = OnVoiceStream;
            Hook();
            Log("Emily Companion inicializada.");
        }

        private void Hook()
        {
            ModHooks.HeroUpdateHook += HeroUpdate;
            ModHooks.SceneChanged += SceneChanged;
            ModHooks.TakeDamageHook += TakeDamage;
            ModHooks.AfterTakeDamageHook += AfterTakeDamage;
            ModHooks.BeforePlayerDeadHook += BeforePlayerDead;
            ModHooks.AfterPlayerDeadHook += AfterPlayerDead;
            ModHooks.OnReceiveDeathEventHook += EnemyDeath;
            ModHooks.CharmUpdateHook += CharmUpdate;
            ModHooks.NewGameHook += NewGame;
            ModHooks.SavegameLoadHook += SaveLoaded;
        }

        public void Unload()
        {
            ModHooks.HeroUpdateHook -= HeroUpdate;
            ModHooks.SceneChanged -= SceneChanged;
            ModHooks.TakeDamageHook -= TakeDamage;
            ModHooks.AfterTakeDamageHook -= AfterTakeDamage;
            ModHooks.BeforePlayerDeadHook -= BeforePlayerDead;
            ModHooks.AfterPlayerDeadHook -= AfterPlayerDead;
            ModHooks.OnReceiveDeathEventHook -= EnemyDeath;
            ModHooks.CharmUpdateHook -= CharmUpdate;
            ModHooks.NewGameHook -= NewGame;
            ModHooks.SavegameLoadHook -= SaveLoaded;
            if (_fairy != null) UnityEngine.Object.Destroy(_fairy.gameObject);
            if (_pickup != null) UnityEngine.Object.Destroy(_pickup.gameObject);
            StopSpeech();
            _audioDucker.Restaurar();
            _hud?.Destroy();
            _dialogue?.Dispose();
            _boss?.Dispose();
            _combat?.Dispose();
            _bridge?.Dispose();
            _initialized = false;
        }

        private void HeroUpdate()
        {
            try
            {
                var gm = GameManager.instance;
                var hero = HeroController.instance;
                var pd = PlayerData.instance;
                if (gm == null || hero == null || pd == null) return;
                if (string.IsNullOrEmpty(_sceneId))
                {
                    _sceneSequence++;
                    _sceneId = gm.sceneName + ":" + _sceneSequence;
                }

                var gameplay = gm.IsGameplayScene() && !gm.IsCinematicScene();
                if (!_save.EncontrouEmily && gameplay && _pickup == null &&
                    (gm.sceneName == "Tutorial_01" || gm.sceneName == "Town"))
                    _pickup = EmilyPickup.Create(
                        this, hero.transform.position + new Vector3(4f, 1.2f, 0));

                var active = Active;
                _bridge.Configure(_settings, active);
                if (!active)
                {
                    if (_wasActive) ResetSessionTracking();
                    _wasActive = false;
                    _healthBeforeDamage = -1;
                    StopSpeech();
                    if (_fairy != null) _fairy.gameObject.SetActive(false);
                    _dialogue?.Reset();
                    _boss?.Reset();
                    _combat?.Reset();
                    _hud?.HideAll();
                    DebugKeys();
                    return;
                }

                if (!_wasActive)
                {
                    _wasActive = true;
                    ResetSessionTracking();
                    _boss?.SceneChanged(gm.sceneName);
                }
                // Antes de emitir saudação, área ou progresso: Update não pode
                // limpar estes eventos ao reconhecer uma campanha pela primeira vez.
                _bridge.BindCampaign(CurrentCampaignId());

                // mapZone nem sempre está atualizado no exato callback de cena.
                // Observar também aqui garante que a região nova seja percebida
                // no primeiro frame autoritativo, antes de qualquer fala começar.
                ObserveCurrentZone(gm.sceneName);
                ResolvePendingDamage();
                TickSpeech();
                _audioDucker.Tick(VozTocandoAgora ? DuckDb() : 0f);
                _dialogue?.Tick();
                var campaignId = CurrentCampaignId();
                _bridge.Update(campaignId, _sceneId);
                var atBench = pd.atBench;
                TrackActivity(hero.transform.position, gameplay, atBench);
                _combat?.Tick(hero.transform.position, gameplay && !gm.isPaused);
                _boss?.Tick();
                if (Time.unscaledTime >= _nextProgressCheck)
                {
                    _nextProgressCheck = Time.unscaledTime + .75f;
                    _progress.Observe(pd);
                }
                if (gameplay && _settings.IntegracaoIa && _announcedCampaign != campaignId)
                {
                    _announcedCampaign = campaignId;
                    Emit("jogo_iniciado", new {
                        versao_mod = Version,
                        cena = gm.sceneName,
                        zona = pd.mapZone.ToString(),
                        zona_nome = EmilyLocations.Nome(pd.mapZone.ToString()),
                        vida_maxima = pd.maxHealth,
                        dano_ferrao = pd.nailDamage
                    });
                }
                if (gameplay && _settings.IntegracaoIa && _greetedCampaign != campaignId)
                {
                    // Ele entrou no jogo/save com o vínculo equipado: uma frase de
                    // boas-vindas, curta, em qualquer modo de fala. Persistente
                    // para sobreviver à transição de entrada da cena.
                    _greetedCampaign = campaignId;
                    Emit("boas_vindas", new {
                        cena = gm.sceneName,
                        zona = pd.mapZone.ToString(),
                        zona_nome = EmilyLocations.Nome(pd.mapZone.ToString()),
                        modo_fala = _settings.ModoFala,
                        persistente = true,
                    });
                }
                if (_trackingReady && atBench != _lastBench)
                {
                    _lastBench = atBench;
                    _lastMovementAt = Time.unscaledTime;
                    var newBench = atBench && RememberBench(gm.sceneName);
                    Emit(newBench ? "banco_descoberto" : atBench ? "banco" : "banco_saida", new {
                        nome = newBench ? "um novo banco" : "banco",
                        cena = gm.sceneName,
                        zona = pd.mapZone.ToString(),
                        zona_nome = EmilyLocations.Nome(pd.mapZone.ToString()),
                        vida_atual = pd.health,
                        geo = pd.geo,
                        persistente = newBench
                    });
                }
                if (gameplay && _fairy == null) _fairy = EmilyFairyController.Create(this);
                if (_fairy != null) _fairy.gameObject.SetActive(gameplay);
                if (Time.unscaledTime >= _nextState)
                {
                    _nextState = Time.unscaledTime + 4f;
                    Emit("estado", new {
                        vida_atual = pd.health, vida_maxima = pd.maxHealth,
                        dano_ferrao = pd.nailDamage,
                        alma = pd.MPCharge, geo = pd.geo,
                        cena = gm.sceneName,
                        zona = pd.mapZone.ToString(),
                        zona_nome = EmilyLocations.Nome(pd.mapZone.ToString()), modo_fala = _settings.ModoFala,
                        charm_equipado = true, vinculo = _save.Vinculo,
                        posicao_x = Math.Round(hero.transform.position.x, 2),
                        posicao_y = Math.Round(hero.transform.position.y, 2),
                        distancia_sessao = Math.Round(_distanceThisSession, 1),
                        parado_segundos = Math.Round(CurrentIdleSeconds(gameplay, atBench), 1),
                        tempo_sessao = Math.Round(Time.unscaledTime - _sessionStartedAt, 1),
                        segundos_ativos_delta = Math.Round(ConsumeActiveDelta(), 2),
                        em_gameplay = gameplay,
                        no_banco = atBench,
                        pausado = Time.timeScale <= .01f,
                        habilidades = AbilitySnapshot(),
                        combate = _combat?.Snapshot(),
                        progresso = _progress.Telemetry()
                    });
                }
                MaybeChatter(gameplay, atBench, gm);
                DebugKeys();
                _hud.Update(_save.Vinculo, _bridge.Online,
                    _fairy != null ? _fairy.CooldownSummary() : "aguardando vínculo", _settings.Hud);
            }
            catch (Exception e) { LogError(e); }
        }

        private static string CurrentCampaignId()
        {
            var gm = GameManager.instance;
            return gm == null ? "" : "slot-" + gm.profileID;
        }

        private void TrackActivity(Vector3 position, bool gameplay, bool atBench)
        {
            var now = Time.unscaledTime;
            if (!_trackingReady)
            {
                _trackingReady = true;
                if (_sessionStartedAt <= 0f) _sessionStartedAt = now;
                _lastTrackingAt = now;
                _lastMovementAt = now;
                _lastHeroPosition = position;
                _lastBench = atBench;
                if (atBench) RememberBench(GameManager.instance != null ? GameManager.instance.sceneName : "");
                return;
            }
            var elapsed = Mathf.Clamp(now - _lastTrackingAt, 0f, .5f);
            _lastTrackingAt = now;
            var active = gameplay && !atBench && Time.timeScale > .01f;
            if (active) _activeSinceState += elapsed;
            var moved = Vector2.Distance(position, _lastHeroPosition);
            // Ignora teleporte/troca de cena e tolera pequenos ajustes da física.
            if (active && moved >= .08f && moved <= 6f)
            {
                _distanceThisSession += moved;
                _lastMovementAt = now;
            }
            if (!active) _lastMovementAt = now;
            _lastHeroPosition = position;
        }

        private double ConsumeActiveDelta()
        {
            var value = _activeSinceState;
            _activeSinceState = 0f;
            return value;
        }

        private double CurrentIdleSeconds(bool gameplay, bool atBench)
        {
            if (!gameplay || atBench || Time.timeScale <= .01f) return 0d;
            return Math.Max(0d, Time.unscaledTime - _lastMovementAt);
        }

        private void MaybeChatter(bool gameplay, bool atBench, GameManager gm)
        {
            // Banco deixou de ser exceção: descansar é justamente um bom momento
            // para conversa solta. A rotina de "sentou no banco" não fala mais
            // nada; quem aparece ali é o comentário espontâneo.
            // 0.5.0: tagarela também conversa durante luta de chefe, só que com
            // intervalo maior — quem cobre a briga em si é o boss_luta.
            if (_settings.ModoFala != "tagarela" || !Active || !gameplay ||
                Time.timeScale <= .01f ||
                !PodeFalarAgora() ||
                _currentSpeech != null || _speechQueue.Count > 0)
            {
                if (_settings.ModoFala != "tagarela") _nextChatterAt = 0f;
                return;
            }
            if (_nextChatterAt <= 0f)
            {
                _nextChatterAt = Time.unscaledTime + UnityEngine.Random.Range(110f, 190f);
                return;
            }
            if (Time.unscaledTime < _nextChatterAt) return;
            var inFight = _boss != null && _boss.InFight;
            _nextChatterAt = Time.unscaledTime + (inFight
                ? UnityEngine.Random.Range(100f, 160f)
                : atBench
                    ? UnityEngine.Random.Range(70f, 120f)
                    : UnityEngine.Random.Range(140f, 230f));
            Emit("comentario_tagarela", new {
                cena = gm.sceneName,
                zona = PlayerData.instance.mapZone.ToString(),
                zona_nome = EmilyLocations.NomeDoMapZone(),
                vida_atual = PlayerData.instance.health,
                vida_maxima = PlayerData.instance.maxHealth,
                geo = PlayerData.instance.geo,
                tempo_sessao = Math.Round(Time.unscaledTime - _sessionStartedAt, 1),
                distancia_sessao = Math.Round(_distanceThisSession, 1),
                progresso = _progress.Telemetry(),
                combate = _combat?.Snapshot(),
                prioridade = 18,
            });
        }

        private static object AbilitySnapshot()
        {
            var pd = PlayerData.instance;
            return new {
                dash = pd.GetBool("hasDash"),
                dash_sombrio = pd.GetBool("hasShadowDash"),
                garra = pd.GetBool("hasWalljump"),
                asas = pd.GetBool("hasDoubleJump"),
                super_dash = pd.GetBool("hasSuperDash"),
                lagrima = pd.GetBool("hasAcidArmour"),
                lanterna = pd.GetBool("hasLantern"),
                ferrao_dos_sonhos = pd.GetBool("hasDreamNail")
            };
        }

        private bool RememberBench(string scene)
        {
            if (string.IsNullOrWhiteSpace(scene)) return false;
            if (_save.BancosConhecidos == null) _save.BancosConhecidos = new List<string>();
            if (_save.BancosConhecidos.Contains(scene)) return false;
            _save.BancosConhecidos.Add(scene);
            return true;
        }

        private void DebugKeys()
        {
            if (Input.GetKeyDown(KeyCode.F6)) AcquireEmily();
            if (Active && Input.GetKeyDown(KeyCode.F8)) _fairy?.PulseBond();
            if (Input.GetKeyDown(KeyCode.F9))
                _settings.Hud = _settings.Hud == "detalhado" ? "vinculo" : "detalhado";
        }

        private void SceneChanged(string scene)
        {
            _sceneSequence++;
            _sceneId = scene + ":" + _sceneSequence;
            _pickup = null;
            _trackingReady = false;
            _combat?.Reset();
            _nextState = 0f;
            _dialogue?.Reset();
            DropStaleSpeech();
            if (Active) _boss?.SceneChanged(scene);
            else _boss?.Reset();
            // Tenta reconhecer já no callback. Se mapZone ainda estiver com o
            // valor da sala anterior, HeroUpdate repete a observação no primeiro
            // frame autoritativo e percebe a mudança sem esperar o snapshot.
            if (Active) _bridge?.BindCampaign(CurrentCampaignId());
            ObserveCurrentZone(scene);
        }

        private void ObserveCurrentZone(string scene)
        {
            var zona = PlayerData.instance != null ? PlayerData.instance.mapZone.ToString() : "";
            if (string.IsNullOrEmpty(zona)) return;
            // `area_nova` é evento de REGIÃO, não de sala: andar entre salas da
            // mesma zona não pode virar assunto novo. A primeira cena da sessão
            // apenas situa a Emily, sem gerar comentário de área.
            if (_zonaInicialPendente)
            {
                _zonaInicialPendente = false;
                _zonaVista = zona;
                return;
            }
            if (zona == _zonaVista) return;
            var anterior = _zonaVista;
            _zonaVista = zona;
            Emit("area_nova", new {
                cena = scene,
                zona = zona,
                zona_nome = EmilyLocations.NomeDoMapZone(),
                anterior = anterior,
                regiao_nova = true,
            });
        }

        private int TakeDamage(ref int hazardType, int damage)
        {
            if (!Active)
            {
                _healthBeforeDamage = -1;
                return damage;
            }
            _healthBeforeDamage = PlayerData.instance != null ? PlayerData.instance.health : -1;
            _resolvedIncomingDamage = _fairy != null ? _fairy.ModifyIncomingDamage(damage) : damage;
            return _resolvedIncomingDamage;
        }
        private int AfterTakeDamage(int hazardType, int damage)
        {
            if (!Active)
            {
                _healthBeforeDamage = -1;
                return damage;
            }
            _resolvedIncomingDamage = damage;
            _pendingHazardType = hazardType;
            _pendingDamageAt = Time.unscaledTime;
            return damage;
        }

        private void ResolvePendingDamage()
        {
            if (_healthBeforeDamage < 0 || PlayerData.instance == null) return;
            var currentHealth = PlayerData.instance.health;
            var actualDamage = Math.Max(0, _healthBeforeDamage - currentHealth);
            // O hook chamado "After" roda antes de PlayerData.TakeHealth. Espera
            // ao menos um frame; depois de .3s, vida igual significa bloqueio,
            // invencibilidade ou Escudo da Filha e o evento deve ser descartado.
            if (actualDamage <= 0 && Time.unscaledTime - _pendingDamageAt < .3f) return;
            _healthBeforeDamage = -1;
            if (actualDamage <= 0 || _resolvedIncomingDamage <= 0) return;
            _fairy?.OnPlayerDamaged(currentHealth);
            _boss?.OnPlayerDamaged(actualDamage);
            _lastMovementAt = Time.unscaledTime;
            Emit(currentHealth <= 2 ? "quase_morte" : "dano", new {
                dano = actualDamage,
                vida_atual = currentHealth,
                hazard_tipo_bruto = _pendingHazardType,
                origem = _combat?.SourceName(_pendingDamageAt) ?? "",
                origem_tipo = _combat?.SourceKind(_pendingDamageAt) ?? "desconhecida",
                origem_confirmada = _combat != null && _combat.SourceConfirmed(_pendingDamageAt),
                combate = _combat?.Snapshot(),
                zona = PlayerData.instance.mapZone.ToString(),
                zona_nome = EmilyLocations.NomeDoMapZone(),
            });
        }
        private void BeforePlayerDead()
        {
            if (Active) _fairy?.LastScold();
        }
        private void AfterPlayerDead()
        {
            if (!Active) return;
            _save.MortesPresenciadas++;
            _lastMovementAt = Time.unscaledTime;
            // Persistente porque a Emily agora espera o jogo liberar: a reação
            // precisa sobreviver à tela de morte e ao retorno ao banco.
            Emit("morte", new {
                mortes_presenciadas = _save.MortesPresenciadas,
                // 0.4.10: se ele caiu numa luta de chefe, a Emily presenciou a
                // briga; a reação pós-respawn pode citar o chefe em vez de ser
                // genérica.
                luta = _boss != null ? _boss.LutaRecente() : "",
                zona = PlayerData.instance.mapZone.ToString(),
                zona_nome = EmilyLocations.NomeDoMapZone(),
                persistente = true,
            });
        }

        private void EnemyDeath(EnemyDeathEffects effects, bool already, ref float? direction,
            ref bool reset, ref bool spellBurn, ref bool watery)
        {
            if (!Active || already || effects == null) return;
            _save.InimigosAjudados++;
            _save.Vinculo = Mathf.Clamp(_save.Vinculo + 1, 0, 100);
            Emit("inimigo_morto", new {
                inimigo = effects.gameObject.name, total = _save.InimigosAjudados,
                zona = PlayerData.instance.mapZone.ToString(),
                zona_nome = EmilyLocations.NomeDoMapZone(),
            });
        }

        private void CharmUpdate(PlayerData pd, HeroController hc)
        {
            if (_charm == null) return;
            if (!Active)
            {
                StopSpeech();
                _bridge?.Configure(_settings, false);
            }
        }
        private void NewGame()
        {
            StopSpeech();
            _bridge?.ResetForSave();
            _wasActive = false;
            _save = new EmilySaveSettings();
            _sceneSequence = 0;
            _sceneId = "";
            _greetedCampaign = "";
            _zonaVista = "";
            _zonaInicialPendente = true;
            ResetSessionTracking();
        }
        private void SaveLoaded(int slot)
        {
            _bridge?.ResetForSave();
            ResetSessionTracking();
            _charm?.RestoreCharmState(_save.Charm ?? new EasyCharmState());
            _wasActive = false;
            // Carregar um save conta como entrar no jogo: a saudação volta.
            _greetedCampaign = "";
            _announcedCampaign = "";
            _sceneId = "";
            // Zona zerada aqui (e não no reset de sessão): assim a primeira cena
            // do save só registra onde ele está, e a primeira região realmente
            // nova depois disso volta a ser um evento comentável.
            _zonaVista = "";
            _zonaInicialPendente = true;
            StopSpeech();
        }

        private void ResetSessionTracking()
        {
            _trackingReady = false;
            _healthBeforeDamage = -1;
            _resolvedIncomingDamage = _pendingHazardType = 0;
            _pendingDamageAt = 0f;
            _progress?.Reset();
            _dialogue?.Reset();
            _boss?.Reset();
            _combat?.Reset();
            _nextProgressCheck = 0f;
            _nextChatterAt = 0f;
            _lastAutomaticPowerEvent.Clear();
            _announcedCampaign = "";
            _sessionStartedAt = Time.unscaledTime;
            _lastTrackingAt = _sessionStartedAt;
            _lastMovementAt = _sessionStartedAt;
            _activeSinceState = 0f;
            _distanceThisSession = 0f;
        }

        public void AcquireEmily()
        {
            if (_charm == null) return;
            var first = !_save.EncontrouEmily;
            _save.EncontrouEmily = true;
            _save.Vinculo = Math.Max(_save.Vinculo, 10);
            _charm.GiveCharm(first);
            if (_settings.AutoEquipar) AutoEquip();
            if (Active && _fairy == null) _fairy = EmilyFairyController.Create(this);
            // Acabou de conhecer a Emily: ela fala a fala de aquisição, não a de
            // boas-vindas, então o cumprimento desta sessão já está "usado".
            _greetedCampaign = CurrentCampaignId();
            Emit("charm_adquirido", new {
                charm = "Vínculo de Emily", custo = 0, vinculo = _save.Vinculo,
                persistente = true,
            });
        }

        private void AutoEquip()
        {
            if (_charm == null || PlayerData.instance == null || GameManager.instance == null) return;
            PlayerData.instance.SetBool("gotCharm_" + _charm.Id, true);
            PlayerData.instance.SetBool("equippedCharm_" + _charm.Id, true);
            GameManager.instance.EquipCharm(_charm.Id);
            _save.AutoEquipou = true;
        }

        private void OnSpeech(EmilySpeechItem item)
        {
            if (!Active || item == null || string.IsNullOrWhiteSpace(item.Text)) return;
            if (_speechBySequence.ContainsKey(item.Sequence)) return;
            if (!_settings.Voz)
            {
                item.VoiceExpected = false;
                item.VoiceResolved = true;
            }
            while (_speechQueue.Count >= MaxQueuedSpeech) DropOldestQueuedSpeech();
            EnqueueSpeechOrdered(item);
            _speechBySequence[item.Sequence] = item;
        }


        private void EnqueueSpeechOrdered(EmilySpeechItem novo)
        {
            var items = new List<EmilySpeechItem>(_speechQueue) { novo };
            items.Sort((a, b) => a.Sequence.CompareTo(b.Sequence));
            _speechQueue.Clear();
            foreach (var item in items) _speechQueue.Enqueue(item);
        }

        private void OnVoice(int sequence, byte[] wav)
        {
            EmilySpeechItem item;
            if (!_speechBySequence.TryGetValue(sequence, out item)) return;
            item.PcmStream = null;
            item.Wav = wav;
            item.VoiceResolved = true;
        }

        private void OnVoiceStream(int sequence, EmilyPcmStream pcm)
        {
            EmilySpeechItem item;
            if (!_speechBySequence.TryGetValue(sequence, out item))
            {
                pcm?.Complete();
                return;
            }
            item.PcmStream = pcm;
            item.VoiceResolved = true;
        }

        /// <summary>
        /// Só fala quando o jogo está de fato em jogo: fora de cutscene, diálogo,
        /// transição de tela, fast travel, menu e animações que travam o
        /// Cavaleiro. Fora disso a fala espera em vez de atropelar o momento.
        /// </summary>
        private bool PodeFalarAgora()
        {
            if (!Active) return false;
            var gm = GameManager.instance;
            var hero = HeroController.instance;
            if (gm == null || hero == null) return false;
            if (gm.isPaused || Time.timeScale <= .01f) return false;
            if (gm.IsCinematicScene() || gm.IsStagTravelScene()) return false;
            if (!gm.IsGameplayScene()) return false;
            if (hero.cState.dead || hero.cState.hazardDeath || hero.cState.hazardRespawning) return false;
            if (hero.cState.transitioning) return false;
            if (_dialogue != null && _dialogue.EmDialogo) return false;
            // 0.5.0: durante uma luta de chefe, a luta É o jogo. Bloqueios
            // momentâneos de input (intro, title card, troca de fase) não podem
            // calar a Emily — era exatamente o que fazia a fala do boss sumir.
            if (_boss != null && _boss.InFight) return true;
            if (hero.transitionState != GlobalEnums.HeroTransitionState.WAITING_TO_TRANSITION) return false;
            if (!hero.isHeroInPosition || !hero.acceptingInput) return false;
            return true;
        }

        private float DuckDb()
        {
            if (_settings.Ducking == "forte") return -9f;
            if (_settings.Ducking == "leve") return -5f;
            return 0f;
        }

        private void TickSpeech()
        {
            if (!Active)
            {
                StopSpeech();
                return;
            }
            var agora = Time.unscaledTime;
            if (_currentSpeech == null)
            {
                if (_speechQueue.Count == 0) return;
                _currentSpeech = _speechQueue.Dequeue();
                _voiceWaitUntil = agora + VoiceWaitTimeout;
                _speechStarted = false;
                _holdStartedAt = agora;
            }
            if (!_speechStarted && !SpeechStillFitsCurrentZone(_currentSpeech))
            {
                // A resposta já estava pronta na fila, mas o Vitor atravessou a
                // fronteira de região antes de ela começar. Não fale da área
                // anterior como se ele ainda estivesse lá. Fala iniciada nunca
                // passa por esta regra e continua até o fim.
                FinishSpeech();
                return;
            }
            if (!_speechStarted && !PodeFalarAgora())
            {
                // Regra pedida em jogo: o gate decide apenas se ela pode COMEÇAR.
                // Fala já iniciada passa adiante para verificar o fim do áudio,
                // mesmo durante diálogo, cutscene, pausa ou transição.
                if (agora - _holdStartedAt >=
                    (_currentSpeech.Persistent ? PersistentSpeechHoldLimit : SpeechHoldLimit))
                {
                    // Esperou demais sem nunca poder começar: a linha já perdeu o
                    // contexto, então sai da fila em vez de falar fora de hora.
                    FinishSpeech();
                    return;
                }
                return;
            }
            if (!_settings.Voz && _currentSpeech.VoiceExpected)
            {
                if (_speechStarted)
                {
                    FinishSpeech();
                    return;
                }
                _currentSpeech.VoiceExpected = false;
                _currentSpeech.VoiceResolved = true;
            }
            if (!_currentSpeech.VoiceExpected)
            {
                if (!_speechStarted)
                {
                    StartSpeech(_currentSpeech);
                    return;
                }
                if (Time.unscaledTime >= _speechEndsAt) FinishSpeech();
                return;
            }
            if (_speechStarted)
            {
                if (_voicePlayer != null && !_voicePlayer.SpeechAudible)
                    _hud?.HideSpeech();
                if (_voicePlayer == null || !_voicePlayer.IsPlaying) FinishSpeech();
                return;
            }
            if (!_currentSpeech.VoiceResolved)
            {
                if (Time.unscaledTime >= _voiceWaitUntil) FinishSpeech();
                return;
            }
            if (_currentSpeech.PcmStream != null &&
                !_currentSpeech.PcmStream.Ready)
            {
                if (Time.unscaledTime >= _voiceWaitUntil) FinishSpeech();
                return;
            }
            if (!_speechStarted)
            {
                if (_currentSpeech.PcmStream == null &&
                    (_currentSpeech.Wav == null || _currentSpeech.Wav.Length <= 44))
                {
                    FinishSpeech();
                    return;
                }
                StartSpeech(_currentSpeech);
                return;
            }
        }

        private static bool SpeechStillFitsCurrentZone(EmilySpeechItem item)
        {
            if (item == null || !item.ValidateZone || string.IsNullOrWhiteSpace(item.Zone))
                return true;
            var pd = PlayerData.instance;
            if (pd == null) return true;
            return string.Equals(
                item.Zone, pd.mapZone.ToString(), StringComparison.OrdinalIgnoreCase);
        }

        private void StartSpeech(EmilySpeechItem item)
        {
            var volume = _settings.Volume / 100f;
            // Com o áudio do jogo abaixado, a voz dela ganha um reforço extra
            // para continuar na frente mesmo em luta cheia.
            if (item.VoiceExpected && DuckDb() < 0f) volume *= 1.3f;
            var duration = item.VoiceExpected && _voicePlayer != null
                ? (item.PcmStream != null
                    ? _voicePlayer.PlayStream(item.PcmStream, volume)
                    : _voicePlayer.Play(item.Wav, volume))
                : Mathf.Clamp(3f + item.Text.Length / 18f, 4f, 90f);
            if (duration <= 0f || (item.VoiceExpected &&
                (_voicePlayer == null || !_voicePlayer.IsPlaying)))
            {
                FinishSpeech();
                return;
            }
            _speechStarted = true;
            _speechEndsAt = Time.unscaledTime + duration;
            if (_settings.Legendas) _hud.ShowSpeech(item.Text,
                item.VoiceExpected ? _voicePlayer : null);
            else _hud.HideSpeech();
            _fairy?.SetEmotion(item.Emotion);
            SuggestedAction(item.Suggested);
        }

        private void FinishSpeech()
        {
            _hud?.HideSpeech();
            _voicePlayer?.Stop();
            if (_currentSpeech != null)
                _speechBySequence.Remove(_currentSpeech.Sequence);
            _currentSpeech = null;
            _speechStarted = false;
            _voiceWaitUntil = 0f;
            _speechEndsAt = 0f;
        }

        private void StopSpeech()
        {
            FinishSpeech();
            _speechQueue.Clear();
            _speechBySequence.Clear();
            _audioDucker.Restaurar();
        }

        private bool VozTocandoAgora =>
            _speechStarted && _currentSpeech != null && _settings.Voz &&
            _voicePlayer != null && _voicePlayer.IsPlaying;

        /// <summary>
        /// Purga apenas a fila. Comentário de área antiga não pode COMEÇAR depois
        /// da troca de cena, mas a fala já em andamento continua até o fim.
        /// </summary>
        private void DropStaleSpeech()
        {
            var count = _speechQueue.Count;
            for (var i = 0; i < count; i++)
            {
                var item = _speechQueue.Dequeue();
                if (item.Persistent) _speechQueue.Enqueue(item);
                else _speechBySequence.Remove(item.Sequence);
            }
        }

        private void DropOldestQueuedSpeech()
        {
            if (_speechQueue.Count == 0) return;
            EmilySpeechItem removed = null;
            var count = _speechQueue.Count;
            for (var i = 0; i < count; i++)
            {
                var item = _speechQueue.Dequeue();
                if (removed == null && !item.Persistent) removed = item;
                else _speechQueue.Enqueue(item);
            }
            if (removed == null && _speechQueue.Count > 0) removed = _speechQueue.Dequeue();
            if (removed != null) _speechBySequence.Remove(removed.Sequence);
        }

        private void SuggestedAction(string action)
        {
            if (!Active || _fairy == null || !_settings.SugestoesIa) return;
            if (action == "marcar_alvo") _fairy.MarkNearest();
            else if (action == "pulso_vinculo") _fairy.PulseBond();
        }

        internal void OnPower(string power, string target, bool automatic = false)
        {
            if (!Active) return;
            _save.Vinculo = Mathf.Clamp(_save.Vinculo + 1, 0, 100);
            if (automatic)
            {
                float last;
                if (_lastAutomaticPowerEvent.TryGetValue(power, out last) && Time.unscaledTime - last < 30f)
                    return;
                _lastAutomaticPowerEvent[power] = Time.unscaledTime;
            }
            Emit("poder_usado", new {
                poder = power, alvo = target, vinculo = _save.Vinculo,
                automatico = automatic,
            });
        }
        internal void Emit(string type, object data)
        {
            if (!Active && type != "charm_adquirido") return;
            if (ImportantEvents.Contains(type))
                Log("Marco detectado e enviado: " + type);
            if (_settings.IntegracaoIa) _bridge?.Enqueue(type, _sceneId, data);
        }

        public void OnLoadLocal(EmilySaveSettings settings)
        {
            // OnLoadLocal pode chegar antes de SavegameLoadHook: nunca deixar
            // uma resposta do save anterior tocar com as configurações do novo.
            StopSpeech();
            _bridge?.ResetForSave();
            _greetedCampaign = "";
            _announcedCampaign = "";
            _zonaVista = "";
            _zonaInicialPendente = true;
            _sceneId = "";
            _wasActive = false;
            ResetSessionTracking();
            _save = settings ?? new EmilySaveSettings();
            if (_charm != null) _charm.RestoreCharmState(_save.Charm ?? new EasyCharmState());
        }
        public EmilySaveSettings OnSaveLocal()
        {
            if (_charm != null) _save.Charm = _charm.GetCharmState();
            return _save;
        }

        public void OnLoadGlobal(EmilyGlobalSettings settings)
        {
            _settings = settings ?? new EmilyGlobalSettings();
            _settings.Normalize();
        }

        public EmilyGlobalSettings OnSaveGlobal()
        {
            _settings.Normalize();
            return _settings;
        }

        public bool ToggleButtonInsideMenu => true;

        public List<IMenuMod.MenuEntry> GetMenuData(IMenuMod.MenuEntry? toggleButtonEntry)
        {
            _settings.Normalize();
            var entries = new List<IMenuMod.MenuEntry>();
            if (toggleButtonEntry.HasValue)
            {
                var toggle = toggleButtonEntry.Value;
                toggle.Description = "Aplicação: ao sair da tela de Mods. A Modding API carrega ou descarrega o mod; não precisa reiniciar o jogo.";
                entries.Add(toggle);
            }

            entries.Add(Choice("Quanto Emily comenta",
                new[] { "Silenciosa", "Discreta", "Normal", "Tagarela" },
                "Aplicação: próxima fala. Silenciosa preserva apenas chamadas diretas e momentos críticos; não precisa reiniciar.",
                i => _settings.ModoFala = new[] { "muda", "quieta", "normal", "tagarela" }[i],
                () => IndexOf(new[] { "muda", "quieta", "normal", "tagarela" }, _settings.ModoFala)));

            var catalog = EmilyModelCatalog.Load();
            entries.Add(Choice("Cérebro no Hollow Knight", catalog.Names.ToArray(),
                "Aplicação: próxima fala. Afeta somente o Hollow Knight. O gateway permanente lê o .env; reinicie o serviço e o jogo após mudar a lista.",
                i => _settings.Modelo = catalog.Ids[ClampIndex(i, catalog.Ids.Count)],
                () => catalog.IndexOf(_settings.Modelo)));

            entries.Add(Toggle("Integração com a IA", "Desligada", "Ligada",
                "Aplicação: imediata. Desligada interrompe telemetria, falas e sugestões; movimento e poderes locais continuam offline.",
                v => _settings.IntegracaoIa = v, () => _settings.IntegracaoIa));
            entries.Add(Toggle("Voz da Emily", "Sem voz", "Com voz",
                "Aplicação: próxima fala. As legendas podem continuar ativas; não precisa reiniciar.",
                v => _settings.Voz = v, () => _settings.Voz));
            entries.Add(Choice("Volume da voz", new[] {
                    "0%", "25%", "50%", "75%", "100%", "125%", "150%", "175%", "200%"
                },
                "Aplicação: próxima reprodução. Acima de 100% aplica ganho com limitador suave para aumentar a voz sem estourar bruscamente; não precisa reiniciar.",
                i => _settings.Volume = new[] { 0, 25, 50, 75, 100, 125, 150, 175, 200 }[i],
                () => ClosestVolumeIndex(_settings.Volume)));
            entries.Add(Toggle("Legendas", "Ocultas", "Visíveis",
                "Aplicação: próxima fala; não precisa reiniciar.",
                v => _settings.Legendas = v, () => _settings.Legendas));
            entries.Add(Choice("Foco na voz da Emily",
                new[] { "Desligado", "Leve", "Forte" },
                "Aplicação: imediata. Abaixa o áudio do jogo (música e efeitos) somente enquanto ela fala, para a voz dela não sumir no meio da luta; o volume volta ao normal assim que a fala termina.",
                i => _settings.Ducking = new[] { "desligado", "leve", "forte" }[i],
                () => IndexOf(new[] { "desligado", "leve", "forte" }, _settings.Ducking)));
            entries.Add(Choice("HUD do vínculo", new[] { "Oculto", "Só vínculo", "Detalhado" },
                "Aplicação: imediata; não precisa reiniciar.",
                i => _settings.Hud = new[] { "oculto", "vinculo", "detalhado" }[i],
                () => IndexOf(new[] { "oculto", "vinculo", "detalhado" }, _settings.Hud)));
            entries.Add(Toggle("Ataques automáticos", "Desativados", "Ativados",
                "Aplicação: imediata. Controla a Faísca Teimosa automática; não precisa trocar de cena.",
                v => _settings.AtaquesAutomaticos = v, () => _settings.AtaquesAutomaticos));
            entries.Add(Toggle("Poderes ofensivos", "Desativados", "Ativados",
                "Aplicação: imediata. Controla Marca de Caça, Pulso do Vínculo e Última Bronca.",
                v => _settings.PoderesOfensivos = v, () => _settings.PoderesOfensivos));
            entries.Add(Toggle("Poderes de suporte", "Desativados", "Ativados",
                "Aplicação: imediata. Controla Escudo da Filha e Eco de Alma.",
                v => _settings.PoderesSuporte = v, () => _settings.PoderesSuporte));
            entries.Add(Toggle("Sugestões de ação da IA", "Ignorar", "Permitir",
                "Aplicação: imediata. Permite que a personalidade sugira Marca/Pulso; cooldowns e toggles locais continuam soberanos.",
                v => _settings.SugestoesIa = v, () => _settings.SugestoesIa));
            entries.Add(Toggle("Autoequipar o vínculo", "Não", "Sim",
                "Aplicação: na próxima aquisição. Depois disso, equipar ou desequipar manualmente é respeitado e salvo.",
                v => _settings.AutoEquipar = v, () => _settings.AutoEquipar));
            return entries;
        }

        private static IMenuMod.MenuEntry Choice(string name, string[] values, string description,
            Action<int> saver, Func<int> loader) =>
            new IMenuMod.MenuEntry(name, values, description, saver, loader);

        private static IMenuMod.MenuEntry Toggle(string name, string off, string on, string description,
            Action<bool> saver, Func<bool> loader) =>
            Choice(name, new[] { off, on }, description, i => saver(i == 1), () => loader() ? 1 : 0);

        private static int IndexOf(string[] values, string value)
        {
            var index = Array.IndexOf(values, value);
            return index >= 0 ? index : 0;
        }

        private static int ClampIndex(int index, int count) => Math.Max(0, Math.Min(count - 1, index));

        private static int ClosestVolumeIndex(int volume)
        {
            var values = new[] { 0, 25, 50, 75, 100, 125, 150, 175, 200 };
            var best = 0;
            for (var i = 1; i < values.Length; i++)
                if (Math.Abs(values[i] - volume) < Math.Abs(values[best] - volume)) best = i;
            return best;
        }
    }
}