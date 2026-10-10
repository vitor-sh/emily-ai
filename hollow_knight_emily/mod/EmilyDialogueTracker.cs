using System;
using System.Collections.Generic;
using System.Reflection;
using System.Text.RegularExpressions;
using UnityEngine;

namespace EmilyCompanion
{
    /// <summary>
    /// Observa a caixa de diálogo real. O hook de fim de conversa do jogo
    /// dispara no fim da digitação de CADA página, então o comentário só sai
    /// quando a caixa é realmente fechada e o Cavaleiro volta a andar.
    /// </summary>
    internal sealed class EmilyDialogueTracker : IDisposable
    {
        private const float DialogueEndDebounce = 1.6f;
        private const float DialogueCooldown = 180f;
        private const float PendingLifetime = 150f;

        private readonly EmilyCompanionMod _mod;
        private readonly Dictionary<string, float> _lastEmitted =
            new Dictionary<string, float>(StringComparer.OrdinalIgnoreCase);

        private static readonly FieldInfo HiddenField = typeof(DialogueBox)
            .GetField("hidden", BindingFlags.Instance | BindingFlags.NonPublic);
        private static readonly FieldInfo TypingField = typeof(DialogueBox)
            .GetField("typing", BindingFlags.Instance | BindingFlags.NonPublic);

        private PendingConversation _pending;
        private DialogueBox _box;
        private float _closedSince;

        /// <summary>
        /// Verdadeiro enquanto uma conversa está na tela. A Emily usa isso para
        /// não falar por cima do NPC: enquanto o herói está preso no diálogo,
        /// IsConversationClosed continua falso.
        /// </summary>
        public bool EmDialogo => _box != null && !IsConversationClosed();

        private static readonly Dictionary<string, string> NpcNames =
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            {
                { "ELDERBUG", "Inseto Ancião" }, { "QUIRREL", "Quirrel" },
                { "CORNIFER", "Cornifer" }, { "ISELDA", "Iselda" },
                { "SLY", "Sly" }, { "SALUBRA", "Salubra" },
                { "ZOTE", "Zote" }, { "BRETTA", "Bretta" },
                { "TISO", "Tiso" }, { "CLOTH", "Cloth" },
                { "MYLA", "Myla" }, { "MIDWIFE", "Parteira" },
                { "MASKMAKER", "Criador de Máscaras" }, { "NAILSMITH", "Ferreiro" },
                { "NAILMASTER_MATO", "Mato" }, { "NAILMASTER_ORO", "Oro" },
                { "NAILMASTER_SHEO", "Sheo" }, { "MATO", "Mato" },
                { "ORO", "Oro" }, { "SHEO", "Sheo" },
                { "LEG_EATER", "Come-Pernas" }, { "LEGEEATER", "Come-Pernas" },
                { "DIVINE", "Divina" }, { "GRIMM", "Grimm" },
                { "NYMM", "Nymm" }, { "JIJI", "Jiji" }, { "JINN", "Jinn" },
                { "SEER", "Vidente" }, { "HUNTER", "Caçador" },
                { "SHAMAN", "Xamã Caracol" }, { "STAG", "Último Besouro" },
                { "DUNG_DEFENDER", "Defensor do Esterco" },
                { "WHITE_LADY", "Dama Branca" }, { "QUEEN", "Dama Branca" },
                { "EMILITIA", "Emilitia" }, { "MARMU", "Marmu" },
            };

        public EmilyDialogueTracker(EmilyCompanionMod mod)
        {
            _mod = mod;
            On.DialogueBox.StartConversation += StartConversation;
            On.DialogueBox.SetConversation += SetConversation;
            On.DialogueBox.ShowPage += ShowPage;
            On.DialogueBox.ShowNextPage += ShowNextPage;
            On.DialogueBox.HideText += HideText;
            On.DialogueBox.SendPageEndEvent += PageEnd;
            On.DialogueBox.SendConvEndEvent += EndConversation;
        }

        private void StartConversation(
            On.DialogueBox.orig_StartConversation orig, DialogueBox self,
            string convName, string sheetName)
        {
            orig(self, convName, sheetName);
            Capture(self, convName, sheetName);
        }

        private void SetConversation(
            On.DialogueBox.orig_SetConversation orig, DialogueBox self,
            string convName, string sheetName)
        {
            orig(self, convName, sheetName);
            Capture(self, convName, sheetName);
        }

        private void Capture(DialogueBox self, string convName, string sheetName)
        {
            MarkActivity(self);
            if (self == null || string.IsNullOrWhiteSpace(convName)) return;
            var text = ResolveText(convName, sheetName);
            if (string.IsNullOrWhiteSpace(text)) return;
            _pending = new PendingConversation {
                Key = convName,
                Sheet = sheetName ?? "",
                Text = text,
                Npc = ResolveNpc(convName, sheetName),
                StartedAt = Time.unscaledTime,
            };
        }

        private void ShowPage(On.DialogueBox.orig_ShowPage orig, DialogueBox self, int pageNum)
        {
            orig(self, pageNum);
            MarkActivity(self);
        }

        private void ShowNextPage(On.DialogueBox.orig_ShowNextPage orig, DialogueBox self)
        {
            orig(self);
            MarkActivity(self);
        }

        private void HideText(On.DialogueBox.orig_HideText orig, DialogueBox self)
        {
            orig(self);
            MarkActivity(self);
        }

        private void PageEnd(On.DialogueBox.orig_SendPageEndEvent orig, DialogueBox self)
        {
            orig(self);
            MarkActivity(self);
        }

        /// <summary>
        /// "CONVERSATION_END" também chega no fim de cada página, então aqui só
        /// marcamos atividade: o comentário sai no Tick, com a caixa fechada.
        /// </summary>
        private void EndConversation(On.DialogueBox.orig_SendConvEndEvent orig, DialogueBox self)
        {
            orig(self);
            MarkActivity(self);
        }

        public void Tick()
        {
            var pendente = _pending;
            if (pendente == null) return;
            if (Time.unscaledTime - pendente.StartedAt > PendingLifetime)
            {
                _pending = null;
                _closedSince = 0f;
                return;
            }
            if (!IsConversationClosed())
            {
                _closedSince = 0f;
                return;
            }
            if (_closedSince <= 0f)
            {
                _closedSince = Time.unscaledTime;
                return;
            }
            if (Time.unscaledTime - _closedSince < DialogueEndDebounce) return;
            _pending = null;
            _closedSince = 0f;
            MaybeEmitConversation(pendente);
        }

        private bool IsConversationClosed()
        {
            var hero = HeroController.instance;
            if (hero == null || !hero.acceptingInput) return false;
            if (_box == null) return true;
            if (ReadFlag(TypingField, _box) == true) return false;
            var hidden = ReadFlag(HiddenField, _box);
            return hidden ?? true;
        }

        private void MaybeEmitConversation(PendingConversation conversa)
        {
            var dedupKey = conversa.Sheet + ":" + conversa.Key + ":" + conversa.Text;
            float last;
            if (_lastEmitted.TryGetValue(dedupKey, out last) &&
                Time.unscaledTime - last < DialogueCooldown) return;
            _lastEmitted[dedupKey] = Time.unscaledTime;
            if (_lastEmitted.Count > 128) PruneEmitted();
            _mod.Emit("npc_dialogo", new {
                nome = conversa.Npc,
                identidade_confirmada = !string.IsNullOrWhiteSpace(conversa.Npc),
                fala = conversa.Text,
                conversa = conversa.Key,
                planilha = conversa.Sheet,
                conversa_encerrada = true,
                prioridade = 62,
            });
        }

        private void MarkActivity(DialogueBox self)
        {
            if (self != null) _box = self;
            _closedSince = 0f;
        }

        private void PruneEmitted()
        {
            var cutoff = Time.unscaledTime - DialogueCooldown;
            var expirados = new List<string>();
            foreach (var pair in _lastEmitted)
                if (pair.Value < cutoff) expirados.Add(pair.Key);
            foreach (var chave in expirados) _lastEmitted.Remove(chave);
        }

        private static bool? ReadFlag(FieldInfo field, DialogueBox box)
        {
            if (field == null || box == null) return null;
            try { return (bool)field.GetValue(box); }
            catch { return null; }
        }

        private static string ResolveText(string convName, string sheetName)
        {
            try
            {
                var text = global::Language.Language.Get(convName, sheetName ?? "");
                if (string.IsNullOrWhiteSpace(text) || text == convName) return "";
                text = Regex.Replace(text, @"<[^>]+>", " ");
                text = text.Replace("#!#", " ").Replace("<br>", " ");
                text = Regex.Replace(text, @"\s+", " ").Trim();
                return text.Length <= 1200 ? text : text.Substring(0, 1200);
            }
            catch { return ""; }
        }

        private static string ResolveNpc(string convName, string sheetName)
        {
            var searchable = ((convName ?? "") + " " + (sheetName ?? ""))
                .Replace('-', '_').Replace(' ', '_').ToUpperInvariant();
            foreach (var pair in NpcNames)
                if (searchable.Contains(pair.Key)) return pair.Value;
            return "";
        }

        public void Reset()
        {
            _pending = null;
            _box = null;
            _closedSince = 0f;
        }

        public void Dispose()
        {
            On.DialogueBox.StartConversation -= StartConversation;
            On.DialogueBox.SetConversation -= SetConversation;
            On.DialogueBox.ShowPage -= ShowPage;
            On.DialogueBox.ShowNextPage -= ShowNextPage;
            On.DialogueBox.HideText -= HideText;
            On.DialogueBox.SendPageEndEvent -= PageEnd;
            On.DialogueBox.SendConvEndEvent -= EndConversation;
            Reset();
            _lastEmitted.Clear();
        }

        private sealed class PendingConversation
        {
            public string Key = "";
            public string Sheet = "";
            public string Text = "";
            public string Npc = "";
            public float StartedAt;
        }
    }
}