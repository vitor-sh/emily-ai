using System;
using System.Collections.Concurrent;
using SFCore.Utils;
using UnityEngine;

namespace EmilyCompanion
{
    /// <summary>Fila PCM16 alimentada pela rede e consumida pela thread de áudio.</summary>
    internal sealed class EmilyPcmStream
    {
        private readonly ConcurrentQueue<float> _samples = new ConcurrentQueue<float>();
        private readonly object _tailLock = new object();
        private int _tail = -1;
        private volatile bool _complete;
        private long _received;
        private long _lastDataReadAt;
        private long _lastAppendAt;

        public readonly int SampleRate;
        public readonly int Channels;
        // Começa com 1s de buffer em vez de esperar dois segundos inteiros.
        public bool Ready => _received >= SampleRate * Channels ||
            (_complete && _received > 0);
        public bool HasData => _received > 0;
        public bool Completed => _complete;
        public long TotalSamples => _received;
        public bool Drained => _complete && _samples.IsEmpty &&
            DateTime.UtcNow.Ticks - _lastDataReadAt >= TimeSpan.TicksPerMillisecond * 150;
        // A rede sumiu no meio da fala: sem Completion e sem dado novo, a voz
        // precisa devolver o controle da fila em vez de tocar silêncio eterno.
        public bool Stalled => !_complete && _samples.IsEmpty &&
            DateTime.UtcNow.Ticks - _lastAppendAt >=
            TimeSpan.TicksPerMillisecond * 10000;

        public EmilyPcmStream(int sampleRate, int channels)
        {
            SampleRate = Math.Max(8000, sampleRate);
            Channels = Math.Max(1, channels);
            _lastAppendAt = DateTime.UtcNow.Ticks;
        }

        public void Append(byte[] bytes, int count)
        {
            if (bytes == null || count <= 0 || _complete) return;
            _lastAppendAt = DateTime.UtcNow.Ticks;
            lock (_tailLock)
            {
                var i = 0;
                if (_tail >= 0 && count > 0)
                {
                    EnqueueSample((short)(_tail | (bytes[0] << 8)));
                    _tail = -1;
                    i = 1;
                }
                for (; i + 1 < count; i += 2)
                    EnqueueSample((short)(bytes[i] | (bytes[i + 1] << 8)));
                if (i < count) _tail = bytes[i];
            }
        }

        private void EnqueueSample(short value)
        {
            _samples.Enqueue(value / 32768f);
            System.Threading.Interlocked.Increment(ref _received);
        }

        public void Complete()
        {
            _complete = true;
            lock (_tailLock) { _tail = -1; }
        }

        public void Read(float[] data, float gain)
        {
            var boost = Mathf.Max(1f, gain);
            var normalization = boost > 1f ? (float)Math.Tanh(boost) : 1f;
            var leu = false;
            for (var i = 0; i < data.Length; i++)
            {
                float value;
                if (_samples.TryDequeue(out value)) leu = true;
                else value = 0f;
                if (boost > 1f) value = (float)Math.Tanh(value * boost) / normalization;
                data[i] = value;
            }
            if (leu) _lastDataReadAt = DateTime.UtcNow.Ticks;
        }
    }

    /// <summary>
    /// Reproduz uma única voz por vez. A legenda acompanha o clipe: entra junto
    /// com o áudio e sai exatamente quando o áudio termina.
    /// </summary>
    internal sealed class EmilyVoicePlayer
    {
        private GameObject _holder;
        private AudioSource _source;
        private AudioClip _clip;
        private EmilyPcmStream _stream;
        private float _streamGain = 1f;

        // A legenda segue a duração das amostras, não a folga de segurança
        // usada para não cortar o final do som no buffer interno do Unity.
        // Durante uma pausa de rede não esconda uma legenda que ainda pode
        // continuar: só sabemos onde a fala termina depois do EOF do stream.
        public bool SpeechAudible => IsPlaying && (_stream == null ||
            !_stream.Completed || PlayedSamples < _stream.TotalSamples);

        private long PlayedSamples =>
            (long)(_source.time * _stream.SampleRate) * _stream.Channels;

        public bool IsPlaying
        {
            get
            {
                if (_source == null || _clip == null || !_source.isPlaying) return false;
                if (_stream == null) return true;
                if (_stream.Stalled) return false;
                if (!_stream.Completed) return true;
                // O Unity lê o PCM com antecedência. A folga pertence só à
                // reprodução: removê-la cortava a cauda audível em alguns clips.
                var total = _stream.TotalSamples;
                if (total <= 0) return false;
                var folga = _stream.SampleRate / 4L * _stream.Channels;
                return PlayedSamples < total + folga;
            }
        }

        public float Play(byte[] wav, float volume)
        {
            Stop();
            if (wav == null || wav.Length <= 44) return 0f;
            try
            {
                _clip = WavUtils.ToAudioClip(wav, "Emily Voice");
                ApplyGain(_clip, Mathf.Max(0f, volume));
                _holder = new GameObject("Emily Voice");
                UnityEngine.Object.DontDestroyOnLoad(_holder);
                _source = _holder.AddComponent<AudioSource>();
                _source.spatialBlend = 0f;
                _source.playOnAwake = false;
                _source.volume = Mathf.Clamp01(volume);
                _source.clip = _clip;
                _source.Play();
                return _clip.length;
            }
            catch (Exception e)
            {
                Modding.Logger.LogWarn("Não foi possível tocar a voz da Emily: " + e.Message);
                Stop();
                return 0f;
            }
        }

        public float PlayStream(EmilyPcmStream pcm, float volume)
        {
            Stop();
            if (pcm == null) return 0f;
            try
            {
                _stream = pcm;
                _streamGain = Mathf.Max(0f, volume);
                // O clip é circular e streaming; IsPlaying encerra a fala quando
                // a rede terminou e a fila de amostras foi drenada.
                _clip = AudioClip.Create(
                    "Emily Voice Stream", pcm.SampleRate * 300, pcm.Channels,
                    pcm.SampleRate, true, OnPcmRead);
                _holder = new GameObject("Emily Voice Stream");
                UnityEngine.Object.DontDestroyOnLoad(_holder);
                _source = _holder.AddComponent<AudioSource>();
                _source.spatialBlend = 0f;
                _source.playOnAwake = false;
                _source.loop = true;
                _source.volume = Mathf.Clamp01(volume);
                if (volume > 1f) _source.volume = 1f;
                _source.clip = _clip;
                _source.Play();
                return 300f;
            }
            catch (Exception e)
            {
                Modding.Logger.LogWarn("Não foi possível tocar o stream da Emily: " + e.Message);
                Stop();
                return 0f;
            }
        }

        private void OnPcmRead(float[] data)
        {
            if (_stream == null)
            {
                Array.Clear(data, 0, data.Length);
                return;
            }
            _stream.Read(data, _streamGain);
        }

        public void Stop()
        {
            if (_source != null)
            {
                try { _source.Stop(); } catch { }
            }
            if (_holder != null) UnityEngine.Object.Destroy(_holder);
            if (_clip != null) UnityEngine.Object.Destroy(_clip);
            _source = null;
            _holder = null;
            _clip = null;
            _stream = null;
            _streamGain = 1f;
        }

        private static void ApplyGain(AudioClip clip, float requestedVolume)
        {
            if (clip == null || requestedVolume <= 1f) return;
            try
            {
                var samples = new float[clip.samples * clip.channels];
                if (!clip.GetData(samples, 0)) return;
                var gain = Mathf.Clamp(requestedVolume, 1f, 2f);
                // tanh funciona como limitador suave: aumenta material baixo e
                // comprime picos gradualmente em vez de recortar em +/-1.
                var normalization = (float)Math.Tanh(gain);
                for (var i = 0; i < samples.Length; i++)
                    samples[i] = (float)Math.Tanh(samples[i] * gain) / normalization;
                clip.SetData(samples, 0);
            }
            catch (Exception e)
            {
                Modding.Logger.LogWarn("Não foi possível amplificar a voz da Emily: " + e.Message);
            }
        }
    }
}