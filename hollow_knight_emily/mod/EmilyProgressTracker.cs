using System;
using System.Collections.Generic;
using System.Linq;

namespace EmilyCompanion
{
    /// <summary>
    /// Compara PlayerData em intervalos curtos. O primeiro retrato de cada save é
    /// apenas linha de base; só transições posteriores viram aquisições.
    /// </summary>
    internal sealed class EmilyProgressTracker
    {
        private readonly EmilyCompanionMod _mod;
        private ProgressSnapshot _previous;
        private ProgressSnapshot _current;

        private static readonly Dictionary<string, string> Abilities = new Dictionary<string, string>
        {
            { "hasDash", "Manto de Asa de Mariposa" },
            { "hasShadowDash", "Manto Sombrio" },
            { "hasWalljump", "Garra de Louva-a-Deus" },
            { "hasDoubleJump", "Asas do Monarca" },
            { "hasSuperDash", "Coração de Cristal" },
            { "hasAcidArmour", "Lágrima de Isma" },
            { "hasDreamNail", "Ferrão dos Sonhos" },
        };

        private static readonly Dictionary<string, string> Stations = new Dictionary<string, string>
        {
            { "openedCrossroads", "Encruzilhada Esquecida" },
            { "openedGreenpath", "Caminho Verde" },
            { "openedFungalWastes", "Ermos Fúngicos" },
            { "openedRuins1", "Cidade das Lágrimas" },
            { "openedRuins2", "Armazéns da Cidade" },
            { "openedRestingGrounds", "Terra do Descanso" },
            { "openedRestingGrounds02", "Terra do Descanso" },
            { "openedRoyalGardens", "Jardins da Rainha" },
            { "openedGardensStagStation", "Jardins da Rainha" },
            { "openedDeepnest", "Ninho Profundo" },
            { "openedHiddenStation", "Estação Escondida" },
            { "openedStagNest", "Ninho dos Besouros" },
        };

        private static readonly Dictionary<string, string> Bosses = new Dictionary<string, string>
        {
            { "killedFalseKnight", "Falso Cavaleiro" },
            { "falseKnightDefeated", "Falso Cavaleiro" },
            { "killedMawlek", "Mawlek Incubador" },
            { "killedHornet", "Hornet" },
            { "killedMegaMossCharger", "Musgo Carregador Gigante" },
            { "killedMantisLord", "Lordes Louva-a-Deus" },
            { "killedMageKnight", "Mestre das Almas" },
            { "killedDungDefender", "Defensor do Esterco" },
            { "killedInfectedKnight", "Receptáculo Quebrado" },
            { "killedMegaBeamMiner", "Guardião de Cristal" },
            { "killedBlackKnight", "Cavaleiros Sentinelas" },
            { "killedTraitorLord", "Lorde Traidor" },
            { "killedHiveKnight", "Cavaleiro da Colmeia" },
            { "killedGrimm", "Grimm" },
            { "killedNightmareGrimm", "Rei do Pesadelo Grimm" },
            { "killedHollowKnight", "Cavaleiro Vazio" },
            { "killedFinalBoss", "Radiância" },
        };

        private static readonly Dictionary<string, string> ImportantItems = new Dictionary<string, string>
        {
            { "hasCityKey", "Brasão da Cidade" },
            { "hasLantern", "Lanterna de Lumélula" },
            { "hasTramPass", "Passe do Bonde" },
            { "hasLoveKey", "Chave do Amor" },
            { "hasKingsBrand", "Marca do Rei" },
            { "hasJournal", "Diário do Caçador" },
        };

        public EmilyProgressTracker(EmilyCompanionMod mod) => _mod = mod;

        public void Reset()
        {
            _previous = null;
            _current = null;
        }

        public void Observe(PlayerData pd)
        {
            if (pd == null) return;
            var next = ProgressSnapshot.Capture(pd);
            _current = next;
            if (_previous == null)
            {
                _previous = next;
                return;
            }

            EmitBoolTransitions(_previous.Bosses, next.Bosses, Bosses, "boss_derrotado");
            EmitSpells(_previous, next);
            EmitStations(_previous, next);
            EmitBoolTransitions(_previous.Items, next.Items, ImportantItems, "item_importante_adquirido");
            EmitCharms(_previous, next);
            EmitBoolTransitions(_previous.Abilities, next.Abilities, Abilities, "habilidade_adquirida");
            _previous = next;
        }

        public object Telemetry()
        {
            var value = _current ?? _previous;
            return value == null ? new { } : value.Telemetry();
        }

        private void EmitBoolTransitions(
            IDictionary<string, bool> before,
            IDictionary<string, bool> after,
            IDictionary<string, string> labels,
            string type)
        {
            var emitted = new HashSet<string>();
            foreach (var pair in labels)
            {
                bool oldValue;
                bool newValue;
                before.TryGetValue(pair.Key, out oldValue);
                after.TryGetValue(pair.Key, out newValue);
                if (!oldValue && newValue && emitted.Add(pair.Value))
                    _mod.Emit(type, new {
                        nome = pair.Value, campo = pair.Key, persistente = true,
                    });
            }
        }

        private void EmitSpells(ProgressSnapshot before, ProgressSnapshot after)
        {
            EmitSpellLevel("fireballLevel", before.Fireball, after.Fireball,
                "Espírito Vingativo", "Alma Sombria");
            EmitSpellLevel("quakeLevel", before.Quake, after.Quake,
                "Mergulho Desolador", "Escuridão Descendente");
            EmitSpellLevel("screamLevel", before.Scream, after.Scream,
                "Espectros Uivantes", "Grito do Abismo");
        }

        private void EmitSpellLevel(string field, int before, int after, string first, string upgraded)
        {
            if (after <= before || after <= 0) return;
            _mod.Emit("magia_adquirida", new {
                nome = after >= 2 ? upgraded : first,
                nivel = after,
                campo = field,
                persistente = true,
            });
        }

        private void EmitStations(ProgressSnapshot before, ProgressSnapshot after)
        {
            var specific = 0;
            foreach (var pair in Stations)
            {
                var oldValue = before.Stations.ContainsKey(pair.Key) && before.Stations[pair.Key];
                var newValue = after.Stations.ContainsKey(pair.Key) && after.Stations[pair.Key];
                if (oldValue || !newValue) continue;
                specific++;
                _mod.Emit("estacao_desbloqueada", new {
                    nome = pair.Value, campo = pair.Key,
                    total = after.StationsOpened, persistente = true,
                });
            }
            if (specific == 0 && after.StationsOpened > before.StationsOpened)
                _mod.Emit("estacao_desbloqueada", new {
                    nome = "uma nova região", total = after.StationsOpened,
                    persistente = true,
                });
        }

        private void EmitCharms(ProgressSnapshot before, ProgressSnapshot after)
        {
            // 0.5.0: Godhome/Panteões não dão amuleto, e o estado interno do
            // jogo oscila nesses cenários (banco do Panteão, troca de elenco).
            // Falso positivo aqui fazia a Emily falar de amuleto que não existiu.
            var scene = GameManager.instance != null
                ? GameManager.instance.sceneName ?? ""
                : "";
            if (scene.StartsWith("GG_", StringComparison.OrdinalIgnoreCase)) return;
            var specific = 0;
            for (var id = 1; id <= 40; id++)
            {
                if (before.Charms.Contains(id) || !after.Charms.Contains(id)) continue;
                specific++;
                _mod.Emit("amuleto_adquirido", new {
                    nome = CharmName(id), amuleto_id = id,
                    total = after.CharmsOwned, persistente = true,
                });
            }
            // 0.5.0: o fallback por contador de CharmsOwned foi removido. Ele
            // disparava amuleto fantasma quando o contador interno oscilava
            // sem nenhuma aquisição real. Só um gotCharm_X novo é aquisição.
        }

        private static string CharmName(int id)
        {
            try
            {
                var key = "CHARM_NAME_" + id;
                var translated = global::Language.Language.Get(key, "UI");
                if (!string.IsNullOrWhiteSpace(translated) && translated != key)
                    return translated;
            }
            catch { }
            return "Amuleto " + id;
        }

        private sealed class ProgressSnapshot
        {
            public Dictionary<string, bool> Abilities;
            public Dictionary<string, bool> Stations;
            public Dictionary<string, bool> Bosses;
            public Dictionary<string, bool> Items;
            public HashSet<int> Charms;
            public int Fireball;
            public int Quake;
            public int Scream;
            public int CharmsOwned;
            public int StationsOpened;

            public static ProgressSnapshot Capture(PlayerData pd)
            {
                return new ProgressSnapshot {
                    Abilities = CaptureBools(pd, EmilyProgressTracker.Abilities.Keys),
                    Stations = CaptureBools(pd, EmilyProgressTracker.Stations.Keys),
                    Bosses = CaptureBools(pd, EmilyProgressTracker.Bosses.Keys),
                    Items = CaptureBools(pd, EmilyProgressTracker.ImportantItems.Keys),
                    Charms = new HashSet<int>(Enumerable.Range(1, 40).Where(
                        id => SafeBool(pd, "gotCharm_" + id))),
                    Fireball = SafeInt(pd, "fireballLevel"),
                    Quake = SafeInt(pd, "quakeLevel"),
                    Scream = SafeInt(pd, "screamLevel"),
                    CharmsOwned = SafeInt(pd, "charmsOwned"),
                    StationsOpened = SafeInt(pd, "stationsOpened"),
                };
            }

            public object Telemetry() => new {
                amuletos_total = CharmsOwned,
                amuletos_ids = Charms.OrderBy(x => x).ToArray(),
                estacoes_total = StationsOpened,
                estacoes = Stations.Where(x => x.Value).Select(x => x.Key).ToArray(),
                bosses_derrotados = Bosses.Where(x => x.Value).Select(x => x.Key).ToArray(),
                itens_importantes = Items.Where(x => x.Value).Select(x => x.Key).ToArray(),
                magias = new { fireballLevel = Fireball, quakeLevel = Quake, screamLevel = Scream },
            };

            private static Dictionary<string, bool> CaptureBools(PlayerData pd, IEnumerable<string> fields)
                => fields.ToDictionary(field => field, field => SafeBool(pd, field));

            private static bool SafeBool(PlayerData pd, string field)
            {
                try { return pd.GetBool(field); }
                catch { return false; }
            }

            private static int SafeInt(PlayerData pd, string field)
            {
                try { return pd.GetInt(field); }
                catch { return 0; }
            }
        }
    }
}