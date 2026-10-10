using System;
using UnityEngine;
using UnityEngine.Audio;

namespace EmilyCompanion
{
    /// <summary>
    /// Abaixa o áudio do jogo apenas enquanto a Emily fala, para a voz dela não
    /// sumir no meio de música, inimigos e efeitos. Usa o parâmetro
    /// "MasterVolume" do mixer do próprio Hollow Knight: o AudioSource da fala
    /// não pertence a nenhum grupo de mixer, então continua no volume normal
    /// enquanto o resto do jogo abaixa. Se o mixer não for localizável, cai para
    /// o volume global do AudioListener, que é o recurso que o próprio jogo usa
    /// para silenciar áudio momentaneamente.
    /// </summary>
    internal sealed class EmilyAudioDucker
    {
        private const string Parametro = "MasterVolume";
        private const float VelocidadeDb = 9f;
        private const float IntervaloBusca = 4f;
        private const int TentativasAntesDoListener = 3;

        private AudioMixer _mixer;
        private bool _usandoListener;
        private int _tentativas;
        private float _proximaBusca;
        private float _baseMixerDb;
        private float _baseListener = 1f;
        private float _offsetDb;
        private bool _aplicando;

        public bool Aplicando => _aplicando;

        /// <summary>Chame todo frame; duckDb é 0 quando não há fala em andamento.</summary>
        public void Tick(float duckDb)
        {
            var alvo = duckDb < 0f ? duckDb : 0f;
            var passo = VelocidadeDb * Mathf.Max(.0001f, Time.unscaledDeltaTime);
            _offsetDb = Mathf.MoveTowards(_offsetDb, alvo, passo);
            if (alvo == 0f && _offsetDb == 0f)
            {
                Restaurar();
                return;
            }
            if (!GarantirAparelho())
            {
                _offsetDb = 0f;
                return;
            }
            Aplicar();
        }

        public void Restaurar()
        {
            if (!_aplicando) return;
            try
            {
                if (_mixer != null) _mixer.SetFloat(Parametro, _baseMixerDb);
                else if (_usandoListener) AudioListener.volume = _baseListener;
            }
            catch (Exception e)
            {
                Modding.Logger.LogWarn("Não consegui devolver o volume do jogo: " + e.Message);
            }
            _aplicando = false;
            _offsetDb = 0f;
        }

        private bool GarantirAparelho()
        {
            if (_mixer != null || _usandoListener) return true;
            if (Time.unscaledTime < _proximaBusca) return false;
            _proximaBusca = Time.unscaledTime + IntervaloBusca;
            var mixer = ProcurarMixer();
            if (mixer != null)
            {
                _mixer = mixer;
                _baseMixerDb = LerDb(mixer);
                _aplicando = true;
                return true;
            }
            _tentativas++;
            if (_tentativas < TentativasAntesDoListener) return false;
            _usandoListener = true;
            _baseListener = AudioListener.volume;
            _aplicando = true;
            return true;
        }

        private void Aplicar()
        {
            try
            {
                if (_mixer != null)
                    _mixer.SetFloat(Parametro, _baseMixerDb + _offsetDb);
                else if (_usandoListener)
                    AudioListener.volume = Mathf.Clamp01(
                        _baseListener * Mathf.Pow(10f, _offsetDb / 20f));
            }
            catch (Exception e)
            {
                Modding.Logger.LogWarn("Não consegui abaixar o áudio do jogo: " + e.Message);
                _mixer = null;
                _usandoListener = false;
                _aplicando = false;
                _offsetDb = 0f;
            }
        }

        private static AudioMixer ProcurarMixer()
        {
            foreach (var slider in Resources.FindObjectsOfTypeAll<MenuAudioSlider>())
                if (UsaParametro(slider != null ? slider.masterMixer : null))
                    return slider.masterMixer;
            foreach (var origem in Resources.FindObjectsOfTypeAll<AudioSource>())
            {
                var grupo = origem != null ? origem.outputAudioMixerGroup : null;
                if (UsaParametro(grupo != null ? grupo.audioMixer : null))
                    return grupo.audioMixer;
            }
            return null;
        }

        private static bool UsaParametro(AudioMixer mixer)
        {
            if (mixer == null) return false;
            try
            {
                float valor;
                return mixer.GetFloat(Parametro, out valor);
            }
            catch { return false; }
        }

        private static float LerDb(AudioMixer mixer)
        {
            try
            {
                float valor;
                return mixer.GetFloat(Parametro, out valor) ? valor : 0f;
            }
            catch { return 0f; }
        }
    }
}