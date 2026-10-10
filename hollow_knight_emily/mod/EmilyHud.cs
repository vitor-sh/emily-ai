using Modding;
using UnityEngine;
using UnityEngine.UI;

namespace EmilyCompanion
{
    // Atualiza mesmo com timeScale = 0: o callback do herói pode parar na pausa,
    // mas o áudio da Emily e a legenda precisam continuar sincronizados.
    public sealed class EmilySpeechFollowVoice : MonoBehaviour
    {
        internal EmilyHud Hud;
        internal EmilyVoicePlayer Voice;

        private void Update()
        {
            if (Voice != null && !Voice.SpeechAudible) Hud?.HideSpeech();
        }
    }

    internal sealed class EmilyHud
    {
        private GameObject _canvas;
        private Text _speech;
        private Text _status;
        private EmilySpeechFollowVoice _voiceSync;
        private float _hideAt;
        public void Ensure()
        {
            if (_canvas != null) return;
            _canvas = CanvasUtil.CreateCanvas(RenderMode.ScreenSpaceOverlay, new Vector2(1920, 1080));
            _canvas.name = "Emily Companion HUD";
            Object.DontDestroyOnLoad(_canvas);
            _voiceSync = _canvas.AddComponent<EmilySpeechFollowVoice>();
            _voiceSync.Hud = this;
            var cg = _canvas.GetComponent<CanvasGroup>();
            cg.blocksRaycasts = false;
            cg.interactable = false;

            var speechGo = CanvasUtil.CreateTextPanel(_canvas, "", 28, TextAnchor.MiddleCenter,
                new CanvasUtil.RectData(new Vector2(1120, 240), new Vector2(0, 105),
                    new Vector2(.5f, 0), new Vector2(.5f, 0)), false);
            _speech = speechGo.GetComponent<Text>();
            _speech.color = new Color(.98f, .9f, 1f, 1f);
            _speech.horizontalOverflow = HorizontalWrapMode.Wrap;
            _speech.verticalOverflow = VerticalWrapMode.Overflow;
            var shadow = speechGo.AddComponent<Shadow>();
            shadow.effectColor = new Color(.18f, .02f, .25f, .95f);
            shadow.effectDistance = new Vector2(2, -2);

            var statusGo = CanvasUtil.CreateTextPanel(_canvas, "", 18, TextAnchor.UpperRight,
                new CanvasUtil.RectData(new Vector2(600, 90), new Vector2(-28, -24),
                    new Vector2(1, 1), new Vector2(1, 1), new Vector2(1, 1)), false);
            _status = statusGo.GetComponent<Text>();
            _status.color = new Color(.75f, .58f, .95f, .92f);
        }

        public void Say(string text, float seconds = 7f)
        {
            Ensure();
            _speech.text = text ?? "";
            _hideAt = Time.unscaledTime + Mathf.Max(2f, seconds);
        }

        public void ShowSpeech(string text, EmilyVoicePlayer voice = null)
        {
            Ensure();
            _speech.text = text ?? "";
            _hideAt = 0f;
            _voiceSync.Voice = voice;
        }

        public void HideSpeech()
        {
            if (_speech != null) _speech.text = "";
            _hideAt = 0f;
            if (_voiceSync != null) _voiceSync.Voice = null;
        }

        public void HideAll()
        {
            HideSpeech();
            if (_status != null) _status.text = "";
        }

        public void Update(int bond, bool online, string power, string mode)
        {
            Ensure();
            if (_speech != null && _hideAt > 0 && Time.unscaledTime >= _hideAt) _speech.text = "";
            if (mode == "oculto") _status.text = "";
            else if (mode == "detalhado") _status.text =
                $"EMILY  vínculo {bond}/100  {(online ? "conectada" : "offline")}\n{power}";
            else _status.text =
                $"◆ {bond}%";
        }

        public void Destroy()
        {
            if (_canvas != null) Object.Destroy(_canvas);
            _canvas = null;
            _voiceSync = null;
        }
    }
}