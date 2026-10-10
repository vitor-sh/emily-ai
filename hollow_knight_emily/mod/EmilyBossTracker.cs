using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using UnityEngine;

namespace EmilyCompanion
{
    /// <summary>
    /// Observa arenas e alvos reais de chefe. As métricas usam HP removido após
    /// HealthManager.Hit, nunca animações, nomes de ataques ou estimativas.
    /// </summary>
    internal sealed class EmilyBossTracker : IDisposable
    {
        private readonly EmilyCompanionMod _mod;
        private readonly HashSet<HealthManager> _bosses = new HashSet<HealthManager>();
        private string _scene = "";
        private string _name = "";
        private bool _encounterAnnounced;
        private bool _fightActive;
        private bool _arenaEvaluated;
        private float _fightAt, _lastDamageAt, _lastCommentAt, _nextScan;
        private int _hits, _hitsWindow, _dealt, _dealtWindow, _taken, _takenWindow;
        // 0.4.10: barra de vida do chefe (pico vs atual) e etapa anunciada da luta.
        private int _hpPeak;
        private int _etapaAnunciada;
        private string _lastFightName = "";
        private float _lastFightEndedAt = -1000f;

        private static readonly Dictionary<string, string> Arenas =
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            {
                { "Crossroads_10", "Falso Cavaleiro" },
                { "Fungus1_04", "Hornet" },
                { "Fungus2_15", "Lordes Louva-a-Deus" },
                { "Ruins1_24", "Mestre das Almas" },
                { "Waterways_05", "Defensor do Esterco" },
                { "Waterways_12", "Flukemarm" },
                { "Deepnest_32", "Nosk" },
                { "Deepnest_East_Hornet", "Hornet" },
                { "Mines_18", "Guardião de Cristal" },
                { "Ruins2_03", "Cavaleiros Sentinelas" },
                { "Abyss_19", "Receptáculo Quebrado" },
                { "Fungus3_23", "Lorde Traidor" },
                { "Fungus3_40", "Marmu" },
                { "Hive_05", "Cavaleiro da Colmeia" },
                { "Room_Final_Boss_Core", "Cavaleiro Vazio" },
                { "Dream_Final_Boss", "Radiância" },
                { "Grimm_Main_Tent", "Grimm" },
                { "Grimm_Nightmare", "Rei do Pesadelo Grimm" },
                { "Dream_01_False_Knight", "Campeão Fracassado" },
                { "Dream_02_Mage_Lord", "Tirano das Almas" },
                { "Dream_03_Infected_Knight", "Parente Perdido" },
                { "Dream_04_White_Defender", "Defensor Branco" },
                { "GG_False_Knight", "Falso Cavaleiro" },
                { "GG_Hornet_1", "Hornet" }, { "GG_Hornet_2", "Hornet" },
                { "GG_Mantis_Lords", "Lordes Louva-a-Deus" },
                { "GG_Mage_Knight", "Mestre das Almas" },
                { "GG_Dung_Defender", "Defensor do Esterco" },
                { "GG_Brooding_Mawlek", "Mawlek Incubador" },
                { "GG_Mega_Moss_Charger", "Musgo Carregador Gigante" },
                { "GG_Crystal_Guardian", "Guardião de Cristal" },
                { "GG_Crystal_Guardian_2", "Guardião Enfurecido" },
                { "GG_Watcher_Knights", "Cavaleiros Sentinelas" },
                { "GG_Traitor_Lord", "Lorde Traidor" },
                { "GG_Hive_Knight", "Cavaleiro da Colmeia" },
                { "GG_Collector", "Colecionador" },
                { "GG_Flukemarm", "Flukemarm" }, { "GG_Nosk", "Nosk" },
                { "GG_Nosk_Hornet", "Nosk Alado" }, { "GG_Uumuu", "Uumuu" },
                { "GG_Grey_Prince_Zote", "Príncipe Cinza Zote" },
                { "GG_White_Defender", "Defensor Branco" },
                { "GG_Grimm", "Grimm" },
                { "GG_Grimm_Nightmare", "Rei do Pesadelo Grimm" },
                { "GG_Hollow_Knight", "Receptáculo Puro" },
                { "GG_Radiance", "Radiância Absoluta" },
                // 0.4.9: arenas de Godhome que faltavam, confirmadas nos dados do
                // próprio jogo (cenas reais no globalgamemanagers). Os Panteões
                // ficam de fora de propósito: lá o nome vem do chefe que entra,
                // via BossSceneController, e não da cena.
                { "GG_Gruz_Mother", "Mãe Gruz" }, { "GG_Gruz_Mother_V", "Mãe Gruz" },
                { "GG_God_Tamer", "Domadora de Deuses" },
                { "GG_Lost_Kin", "Parente Perdido" },
                { "GG_Failed_Champion", "Campeão Fracassado" },
                { "GG_Soul_Master", "Mestre das Almas" },
                { "GG_Soul_Tyrant", "Tirano das Almas" },
                { "GG_Broken_Vessel", "Receptáculo Quebrado" },
                { "GG_Painter", "Sheo" },
                { "GG_Nailmasters", "Oro e Mato" },
                { "GG_Oblobbles", "Oblobbles" },
                { "GG_Mighty_Zote", "Zote, o Poderoso" },
                { "GG_Ghost_Galien", "Galien" }, { "GG_Ghost_Galien_V", "Galien" },
                { "GG_Ghost_Gorb", "Gorb" }, { "GG_Ghost_Gorb_V", "Gorb" },
                { "GG_Ghost_Hu", "Hu Ancião" },
                { "GG_Ghost_Markoth", "Markoth" }, { "GG_Ghost_Markoth_V", "Markoth" },
                { "GG_Ghost_Marmu", "Marmu" }, { "GG_Ghost_Marmu_V", "Marmu" },
                { "GG_Ghost_No_Eyes", "Sem Olhos" }, { "GG_Ghost_No_Eyes_V", "Sem Olhos" },
                { "GG_Ghost_Xero", "Xero" }, { "GG_Ghost_Xero_V", "Xero" },
                { "GG_Mage_Knight_V", "Mestre das Almas" },
                { "GG_Mantis_Lords_V", "Lordes Louva-a-Deus" },
                { "GG_Nosk_V", "Nosk" }, { "GG_Uumuu_V", "Uumuu" },
                { "GG_Brooding_Mawlek_V", "Mawlek Incubador" },
                { "GG_Collector_V", "Colecionador" },
            };

        private static readonly Dictionary<string, string> ObjectNames =
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            {
                { "False Knight", "Falso Cavaleiro" }, { "Mawlek", "Mawlek Incubador" },
                { "Hornet Boss", "Hornet" }, { "Mega Moss Charger", "Musgo Carregador Gigante" },
                { "Mantis Lord", "Lordes Louva-a-Deus" }, { "Mage Lord", "Mestre das Almas" },
                { "Dung Defender", "Defensor do Esterco" }, { "Fluke Mother", "Flukemarm" },
                { "Infected Knight", "Receptáculo Quebrado" },
                { "Mega Beam Miner", "Guardião de Cristal" },
                { "Black Knight", "Cavaleiros Sentinelas" }, { "Traitor Lord", "Lorde Traidor" },
                { "Hive Knight", "Cavaleiro da Colmeia" }, { "Jar Collector", "Colecionador" },
                { "Nosk", "Nosk" }, { "Uumuu", "Uumuu" },
                { "Grey Prince", "Príncipe Cinza Zote" }, { "White Defender", "Defensor Branco" },
                { "Nightmare Grimm", "Rei do Pesadelo Grimm" }, { "Grimm Boss", "Grimm" },
                { "Hollow Knight Boss", "Cavaleiro Vazio" }, { "Pure Vessel", "Receptáculo Puro" },
                { "Absolute Radiance", "Radiância Absoluta" }, { "Radiance", "Radiância" },
                { "Ghost Warrior Marmu", "Marmu" }, { "Marmu", "Marmu" },
                // 0.4.9: chefes que aparecem em Godhome/Panteões e nas arenas
                // adicionais; sem isso só um "chefe desta arena" genérico saía.
                { "Vengefly King", "Rei Vingavoador" },
                { "Gruz Mother", "Mãe Gruz" },
                { "God Tamer", "Domadora de Deuses" },
                { "Lost Kin", "Parente Perdido" },
                { "Soul Master", "Mestre das Almas" },
                { "Soul Tyrant", "Tirano das Almas" },
                { "Ghost Warrior Galien", "Galien" }, { "Galien", "Galien" },
                { "Ghost Warrior Markoth", "Markoth" }, { "Markoth", "Markoth" },
                { "Ghost Warrior Xero", "Xero" }, { "Xero", "Xero" },
                { "Ghost Warrior No Eyes", "Sem Olhos" },
                { "Ghost Warrior Elder Hu", "Hu Ancião" }, { "Elder Hu", "Hu Ancião" },
                { "Ghost Warrior Gorb", "Gorb" }, { "Gorb", "Gorb" },
                { "Paintmaster Sheo", "Sheo" }, { "Sheo", "Sheo" },
                { "Nail Master Oro", "Oro" }, { "Nail Master Mato", "Mato" },
                { "Nailmaster Oro", "Oro" }, { "Nailmaster Mato", "Mato" },
                { "Oblobble", "Oblobbles" },
                { "Mighty Zote", "Zote, o Poderoso" },
                { "Sly Boss", "Sly" },
            };

        private static readonly Dictionary<string, string[]> DefeatFlags =
            new Dictionary<string, string[]>(StringComparer.OrdinalIgnoreCase)
            {
                { "Crossroads_10", new[] { "falseKnightDefeated", "killedFalseKnight" } },
                { "Fungus1_04", new[] { "hornet1Defeated", "killedHornet" } },
                { "Fungus2_15", new[] { "defeatedMantisLords", "killedMantisLord" } },
                { "Ruins1_24", new[] { "mageLordDefeated", "killedMageKnight" } },
                { "Waterways_05", new[] { "defeatedDungDefender", "killedDungDefender" } },
                { "Waterways_12", new[] { "flukeMotherDefeated", "killedFlukeMother" } },
                { "Deepnest_32", new[] { "killedMimicSpider" } },
                { "Deepnest_East_Hornet", new[] { "hornetOutskirtsDefeated" } },
                { "Mines_18", new[] { "defeatedMegaBeamMiner", "killedMegaBeamMiner" } },
                { "Ruins2_03", new[] { "killedBlackKnight" } },
                { "Abyss_19", new[] { "killedInfectedKnight" } },
                { "Fungus3_23", new[] { "killedTraitorLord" } },
                { "Hive_05", new[] { "killedHiveKnight" } },
                { "Room_Final_Boss_Core", new[] { "killedHollowKnight" } },
                { "Dream_Final_Boss", new[] { "killedFinalBoss" } },
                { "Grimm_Main_Tent", new[] { "killedGrimm" } },
                { "Grimm_Nightmare", new[] { "defeatedNightmareGrimm", "killedNightmareGrimm" } },
                { "Dream_01_False_Knight", new[] { "falseKnightDreamDefeated" } },
                { "Dream_02_Mage_Lord", new[] { "mageLordDreamDefeated" } },
                { "Dream_03_Infected_Knight", new[] { "infectedKnightDreamDefeated" } },
                { "Fungus3_40", new[] { "killedGhostMarmu" } },
            };

        private static readonly FieldInfo UnlockBossSceneField = typeof(HealthManager)
            .GetField("unlockBossScene", BindingFlags.Instance | BindingFlags.NonPublic);

        public bool InFight => _fightActive;

        public EmilyBossTracker(EmilyCompanionMod mod)
        {
            _mod = mod;
            On.HealthManager.Hit += HealthHit;
            On.BossSceneController.Setup += BossSceneSetup;
        }

        public void SceneChanged(string scene)
        {
            Reset();
            _scene = scene ?? "";
            EvaluateArena();
        }

        public void Tick()
        {
            if (Time.unscaledTime < _nextScan) return;
            _nextScan = Time.unscaledTime + .5f;
            EvaluateArena();
            DiscoverBosses();
            _bosses.RemoveWhere(b => b == null || b.GetIsDead());
            if (_fightActive && _bosses.Count == 0)
            {
                _fightActive = false;
                // Luta que acabou (vitória ou saída da arena) ainda vale por uns
                // instantes como contexto, por exemplo para a reação à morte
                // logo depois do respawn no banco.
                _lastFightName = _name;
                _lastFightEndedAt = Time.unscaledTime;
                return;
            }
            if (_fightActive)
            {
                ReanunciaBossSeNecessario();
                VerificarEtapa();
                MaybeComment();
            }
        }

        /// <summary>
        /// 0.4.10: barra de vida do chefe em tempo real, medida nos
        /// HealthManager reais. A fração vira pista qualitativa para os
        /// comentários dela; o número em si nunca chega ao modelo.
        /// </summary>
        private float VidaChefeFrac()
        {
            var atual = _bosses
                .Where(b => b != null && !b.GetIsDead())
                .Sum(b => Math.Max(0, b.hp));
            if (atual > _hpPeak) _hpPeak = atual;
            return _hpPeak > 0 ? Mathf.Clamp01((float)atual / _hpPeak) : 1f;
        }

        private void VerificarEtapa()
        {
            if (!EmGameplayReal() || _bosses.Count == 0) return;
            var fracao = VidaChefeFrac();
            if (_etapaAnunciada < 1 && fracao <= .66f) AnunciarEtapa(1, fracao);
            else if (_etapaAnunciada < 2 && fracao <= .33f) AnunciarEtapa(2, fracao);
        }

        private void AnunciarEtapa(int etapa, float fracao)
        {
            _etapaAnunciada = etapa;
            var nomeEtapa = etapa >= 2 ? "final" : "segunda";
            var dica = etapa >= 2
                ? "a luta entrou na reta final: o chefe mudou de comportamento de novo"
                : "o chefe mudou de comportamento; a luta avançou de etapa";
            // Caso pedido em jogo: na Radiância (Absoluta inclusive) a última
            // etapa é a subida pelas plataformas até o topo.
            if (etapa >= 2 &&
                _name.IndexOf("Radiância", StringComparison.OrdinalIgnoreCase) >= 0)
                dica = "a arena virou uma subida de plataformas: o chefe ficou lá em cima esperando";
            _mod.Emit("boss_fase", new {
                nome = _name, etapa = nomeEtapa, dica = dica,
                combate = _mod.CombatSnapshot(),
                identidade_confirmada = IsKnownBossName(_name),
                vida_chefe_frac = Math.Round(fracao, 2),
                prioridade = 74,
                // 0.5.0: transição de fase trava o input por um instante;
                // persistente deixa a fala esperar o controle voltar.
                persistente = true,
            });
        }

        /// <summary>Nome da luta em andamento ou da última, para contextualizar a morte.</summary>
        public string LutaRecente()
        {
            if (_fightActive && !string.IsNullOrWhiteSpace(_name)) return _name;
            if (!string.IsNullOrWhiteSpace(_lastFightName) &&
                Time.unscaledTime - _lastFightEndedAt <= 120f) return _lastFightName;
            return "";
        }

        public void OnPlayerDamaged(int damage)
        {
            if (damage <= 0 || string.IsNullOrWhiteSpace(_name) || _bosses.Count == 0) return;
            StartFight();
            _taken += damage;
            _takenWindow += damage;
            _lastDamageAt = Time.unscaledTime;
        }

        private void BossSceneSetup(On.BossSceneController.orig_Setup orig, BossSceneController self)
        {
            orig(self);
            if (self == null) return;
            var novos = (self.bosses ?? new HealthManager[0])
                .Where(b => b != null).ToArray();
            // 0.5.0: calcular "mudou" ANTES de registrar, senão o registro
            // já deixa _bosses.Contains() verdadeiro e nenhum boss novo entra
            // no Panteão (toda a lógica dependia disso funcionar).
            var mudou = novos.Any(b => !_bosses.Contains(b));
            foreach (var boss in novos) RegisterBoss(boss, true);
            if (mudou)
            {
                string nome = null;
                foreach (var boss in novos)
                    if (TryRecognize(boss, out nome) &&
                        !string.IsNullOrWhiteSpace(nome)) break;
                var novoNome = !string.IsNullOrWhiteSpace(nome)
                    ? nome
                    : novos.Length > 0 ? InternalBossReference(novos[0]) : _name;
                if (!string.IsNullOrWhiteSpace(novoNome) && novoNome != _name)
                {
                    _name = novoNome;
                    _encounterAnnounced = false;
                }
            }
            AnnounceEncounter();
        }

        private void ReanunciaBossSeNecessario()
        {
            // 0.5.1: substituído por detecção em DiscoverBosses (cobriria só
            // se fightActive fosse true; agora cobre também o setup).
        }

        private void HealthHit(On.HealthManager.orig_Hit orig, HealthManager self, HitInstance hitInstance)
        {
            var hpBefore = self != null ? self.hp : 0;
            orig(self, hitInstance);
            string recognized;
            var authoritative = self != null && (
                _bosses.Contains(self) || HasAuthoritativeBossMarker(self)
            );
            if (self == null || hpBefore <= 0 ||
                (!_bosses.Contains(self) &&
                 (!authoritative && (!HasBossContext(self) || !TryRecognize(self, out recognized)))))
                return;
            RegisterBoss(self, authoritative);
            var actual = Math.Max(0, hpBefore - self.hp);
            if (actual <= 0 || IsEmilySource(hitInstance.Source)) return;
            StartFight();
            _hits++;
            _hitsWindow++;
            _dealt += actual;
            _dealtWindow += actual;
        }

        private void DiscoverBosses()
        {
            foreach (var health in UnityEngine.Object.FindObjectsOfType<HealthManager>())
            {
                string recognized;
                var authoritative = HasAuthoritativeBossMarker(health);
                var recognizedBoss = TryRecognize(health, out recognized);
                if (!authoritative && (!HasBossContext(health) || !recognizedBoss)) continue;
                // 0.5.1: descoberta pré-registro — preciso saber se é um chefe
                // novo NA SEQUÊNCIA (mesma cena de Panteão, Setup não é chamado
                // de novo). Se um nome DIFERENTE do anunciado aparecer entre os
                // vivos, o anúncio precisa recomeçar; sem isso, os chefes 2+
                // do Panteão sempre ficavam invisíveis para a Emily.
                var eraNovo = !_bosses.Contains(health);
                RegisterBoss(health, authoritative);
                if (eraNovo && recognizedBoss && !string.IsNullOrWhiteSpace(recognized))
                {
                    if (_encounterAnnounced && recognized != _name)
                    {
                        Modding.Logger.Log(
                            $"Panteão: novo chefe na mesma sequência: {recognized} (era {_name})");
                        _name = recognized;
                        _encounterAnnounced = false;
                        _etapaAnunciada = 0;
                    }
                    else if (string.IsNullOrWhiteSpace(_name))
                    {
                        _name = recognized;
                    }
                }
            }
            AnnounceEncounter();
        }

        private void EvaluateArena()
        {
            if (_arenaEvaluated || PlayerData.instance == null) return;
            _arenaEvaluated = true;
            _name = IsDefeated(_scene) ? "" : ArenaName(_scene);
            AnnounceEncounter();
        }

        private void RegisterBoss(HealthManager boss, bool authoritative)
        {
            if (boss == null) return;
            _bosses.Add(boss);
            string recognized;
            if (string.IsNullOrWhiteSpace(_name) && TryRecognize(boss, out recognized))
                _name = recognized;
            else if (string.IsNullOrWhiteSpace(_name) && authoritative)
                _name = InternalBossReference(boss);
        }

        private void AnnounceEncounter()
        {
            // 0.5.2: anúncio deve entregar SEMPRE — gate de pausa/cutscene fica
            // no TickSpeech (onde a fala fisicamente toca), não na emissão do
            // evento. O evento aguarda a captura no mod e entrega quando pode.
            if (_encounterAnnounced || string.IsNullOrWhiteSpace(_name)) return;
            _encounterAnnounced = true;
            Modding.Logger.Log("[HK-EMILY] chefe percebido: " + _name);
            _mod.Emit("boss_encontrado", new {
                nome = _name, arena = _scene,
                combate = _mod.CombatSnapshot(),
                identidade_confirmada = IsKnownBossName(_name),
                prioridade = 88,
                persistente = true,
            });
        }

        /// <summary>0.5.2: quando o boss anterior termina, limpa o anúncio.</summary>
        public void OnFightEnd()
        {
            if (!_fightActive && _bosses.Count == 0 &&
                !string.IsNullOrWhiteSpace(_name))
            {
                _encounterAnnounced = false;
            }
        }

        private void StartFight()
        {
            if (_fightActive) return;
            _lastFightName = _name;
            Modding.Logger.Log("[HK-EMILY] luta iniciada com: " + _name);
            AnnounceEncounter();
            _fightActive = true;
            _fightAt = _lastDamageAt = _lastCommentAt = Time.unscaledTime;
            _hpPeak = 0;
            _etapaAnunciada = 0;
            _mod.Emit("boss_iniciado", new {
                nome = _name, arena = _scene,
                combate = _mod.CombatSnapshot(),
                identidade_confirmada = IsKnownBossName(_name),
                vida_total_observada = _bosses.Where(b => b != null).Sum(b => Math.Max(0, b.hp)),
                prioridade = 90,
                // 0.5.0: idem boss_encontrado — sobrevive à intro/title card.
                persistente = true,
            });
        }

        private void MaybeComment()
        {
            if (!EmGameplayReal()) return;
            var now = Time.unscaledTime;
            // 0.5.0: era 60s de intervalo e 25s de briga mínima — numa luta de
            // 5 minutos isso dava no máximo 3 comentários, e com thresholds de
            // padrão que quase nunca batiam, ficava em silêncio. Agora: 35s de
            // intervalo, 12s de briga mínima e padrões mais fáceis de alcançar.
            if (now - _lastCommentAt < 35f || now - _fightAt < 12f) return;
            var noDamage = now - _lastDamageAt;
            string pattern = "";
            if (_hitsWindow >= 5 && noDamage >= 12f) pattern = "sequencia_sem_dano";
            else if (_hitsWindow >= 7 && _dealtWindow > 0) pattern = "pressao_constante";
            else if (_takenWindow > 0 && _hitsWindow >= 5) pattern = "recuperacao_apos_dano";
            // 0.5.0: fallback — a luta já durou um tempo e nenhum padrão bateu;
            // mesmo assim a Emily tem algo a dizer (usando a vida do chefe).
            else if (now - _fightAt >= 40f) pattern = "luta_continua";
            if (string.IsNullOrEmpty(pattern)) return;
            _mod.Emit("boss_luta", new {
                nome = _name, arena = _scene, padrao = pattern,
                combate = _mod.CombatSnapshot(),
                identidade_confirmada = IsKnownBossName(_name),
                duracao_segundos = Math.Round(now - _fightAt, 1),
                golpes_total = _hits, golpes_desde_comentario = _hitsWindow,
                dano_causado = _dealt, dano_causado_desde_comentario = _dealtWindow,
                dano_recebido = _taken, dano_recebido_desde_comentario = _takenWindow,
                segundos_sem_dano = Math.Round(noDamage, 1),
                // 0.4.10: vida do chefe em tempo real como pista qualitativa.
                vida_chefe_frac = Math.Round(VidaChefeFrac(), 2),
                prioridade = 76,
            });
            _lastCommentAt = now;
            _hitsWindow = _dealtWindow = _takenWindow = 0;
        }

        /// <summary>
        /// 0.4.9: chefe só existe em jogo de verdade. Pausa, menu e cenas de
        /// interface podem registrar alvos, mas nunca anunciar nem comentar.
        /// </summary>
        private static bool EmGameplayReal()
        {
            var gm = GameManager.instance;
            return gm != null && !gm.isPaused && Time.timeScale > .01f &&
                gm.IsGameplayScene();
        }

        private static bool IsEmilySource(GameObject source) =>
            source != null && source.name.IndexOf("Emily", StringComparison.OrdinalIgnoreCase) >= 0;

        private static bool TryRecognize(HealthManager health, out string name)
        {
            name = "";
            if (health == null || health.gameObject == null || !health.gameObject.activeInHierarchy) return false;
            var raw = health.gameObject.name ?? "";
            foreach (var pair in ObjectNames)
            {
                if (raw.IndexOf(pair.Key, StringComparison.OrdinalIgnoreCase) < 0) continue;
                name = pair.Value;
                return true;
            }
            return false;
        }

        private static string InternalBossReference(HealthManager health)
        {
            if (health == null || health.gameObject == null) return "chefe desta arena";
            var raw = (health.gameObject.name ?? "").Trim();
            return string.IsNullOrWhiteSpace(raw) ? "chefe desta arena" : raw;
        }

        private static bool IsKnownBossName(string name)
        {
            if (string.IsNullOrWhiteSpace(name)) return false;
            return Arenas.Values.Contains(name) || ObjectNames.Values.Contains(name);
        }

        private static bool HasAuthoritativeBossMarker(HealthManager health)
        {
            if (health == null || UnlockBossSceneField == null) return false;
            try { return UnlockBossSceneField.GetValue(health) != null; }
            catch { return false; }
        }

        private bool HasBossContext(HealthManager health)
        {
            return health != null && (
                _bosses.Contains(health) || !string.IsNullOrWhiteSpace(_name)
            );
        }

        private static bool IsDefeated(string scene)
        {
            if (PlayerData.instance == null) return false;
            string[] flags;
            if (!DefeatFlags.TryGetValue(scene ?? "", out flags)) return false;
            foreach (var flag in flags)
            {
                try
                {
                    if (PlayerData.instance.GetBool(flag)) return true;
                }
                catch { }
            }
            return false;
        }

        private static string ArenaName(string scene)
        {
            string name;
            if (Arenas.TryGetValue(scene ?? "", out name)) return name;
            foreach (var pair in Arenas)
                if ((scene ?? "").StartsWith(pair.Key + "_", StringComparison.OrdinalIgnoreCase)) return pair.Value;
            return "";
        }

        public void Reset()
        {
            _bosses.Clear();
            _scene = _name = "";
            _encounterAnnounced = _fightActive = false;
            _arenaEvaluated = false;
            _fightAt = _lastDamageAt = _lastCommentAt = _nextScan = 0f;
            _hits = _hitsWindow = _dealt = _dealtWindow = _taken = _takenWindow = 0;
            _hpPeak = 0;
            _etapaAnunciada = 0;
        }

        public void Dispose()
        {
            On.HealthManager.Hit -= HealthHit;
            On.BossSceneController.Setup -= BossSceneSetup;
            Reset();
        }
    }
}