using System;
using System.Collections.Generic;
using UnityEngine;

namespace EmilyCompanion
{
    /// <summary>
    /// Retrato barato da luta: objetos reais observados, não nomes de lore
    /// inferidos de sprites ou da região. Nenhuma chamada de IA por amostragem.
    /// </summary>
    internal sealed class EmilyCombatContext : IDisposable
    {
        private readonly Func<bool> _active;
        private readonly Dictionary<int, float> _recentTargets = new Dictionary<int, float>();
        private string _lastTarget = "";
        private float _lastTargetAt;
        private float _nextScan;
        private int _nearby;
        private readonly List<string> _nearbyNames = new List<string>();
        private string _source = "";
        private string _sourceKind = "desconhecida";
        private bool _sourceConfirmed;
        private float _sourceAt;

        public EmilyCombatContext(Func<bool> active)
        {
            _active = active;
            On.HealthManager.Hit += EnemyHit;
            On.HeroController.TakeDamage += HeroDamage;
        }

        private void EnemyHit(On.HealthManager.orig_Hit orig, HealthManager self, HitInstance hit)
        {
            var before = self != null ? self.hp : 0;
            orig(self, hit);
            if (!_active() || self == null || before <= self.hp ||
                hit.Source == null || IsEmily(hit.Source) || !IsPlayerSource(hit.Source)) return;
            _lastTarget = Label(self.gameObject);
            _lastTargetAt = Time.unscaledTime;
            _recentTargets[self.GetInstanceID()] = _lastTargetAt;
        }

        private void HeroDamage(On.HeroController.orig_TakeDamage orig, HeroController self,
            GameObject source, GlobalEnums.CollisionSide side, int amount, int hazardType)
        {
            if (_active())
            {
                // O callback entrega o objeto que causou a colisão. O hook de
                // ModHooks sozinho só entrega hazardType, que NÃO identifica
                // por si só a criatura nem um obstáculo específico.
                _sourceAt = Time.unscaledTime;
                _source = Label(source);
                _sourceConfirmed = source != null && !string.IsNullOrEmpty(_source);
                _sourceKind = "desconhecida";
                if (_sourceConfirmed)
                {
                    var enemy = source.GetComponentInParent<HealthManager>();
                    if (enemy != null && !enemy.GetIsDead())
                    {
                        _source = Label(enemy.gameObject);
                        _sourceKind = "criatura";
                    }
                    else
                    {
                        // O tipo de hazard indica uma mecânica de dano, não a
                        // identidade da fonte. Não afirmar 'espinho' por número.
                        _sourceKind = "objeto";
                    }
                }
            }
            orig(self, source, side, amount, hazardType);
        }

        public string SourceName(float happenedAt) =>
            _sourceConfirmed && Math.Abs(_sourceAt - happenedAt) < .2f ? _source : "";
        public string SourceKind(float happenedAt) =>
            _sourceConfirmed && Math.Abs(_sourceAt - happenedAt) < .2f ? _sourceKind : "desconhecida";
        public bool SourceConfirmed(float happenedAt) =>
            _sourceConfirmed && Math.Abs(_sourceAt - happenedAt) < .2f;

        public void Tick(Vector3 hero, bool gameplay)
        {
            if (!gameplay || !_active() || Time.unscaledTime < _nextScan) return;
            _nextScan = Time.unscaledTime + .9f;
            _nearby = 0;
            _nearbyNames.Clear();
            // HealthManager é uma fonte de candidatos, não prova de hostilidade:
            // só contar quem também tem DamageHero no próprio objeto/filhos,
            // ou quem o jogador atingiu recentemente.
            foreach (var enemy in UnityEngine.Object.FindObjectsOfType<HealthManager>())
            {
                if (enemy == null || !enemy.gameObject.activeInHierarchy || enemy.GetIsDead()) continue;
                if (Vector2.Distance(hero, enemy.transform.position) > 11f) continue;
                float struckAt;
                var struck = _recentTargets.TryGetValue(enemy.GetInstanceID(), out struckAt) &&
                    Time.unscaledTime - struckAt < 12f;
                if (!struck && enemy.GetComponentInChildren<DamageHero>() == null &&
                    enemy.GetComponent<DamageHero>() == null) continue;
                _nearby++;
                var name = Label(enemy.gameObject);
                if (!string.IsNullOrEmpty(name) && !_nearbyNames.Contains(name) && _nearbyNames.Count < 4)
                    _nearbyNames.Add(name);
            }
            var expired = new List<int>();
            foreach (var pair in _recentTargets)
                if (Time.unscaledTime - pair.Value > 12f) expired.Add(pair.Key);
            foreach (var id in expired) _recentTargets.Remove(id);
        }

        public object Snapshot()
        {
            var recent = Time.unscaledTime - _lastTargetAt < 12f;
            return new {
                criaturas_proximas_observadas = _nearby,
                identificadores_proximos = _nearbyNames.ToArray(),
                alvo_atingido_recente = recent ? _lastTarget : "",
                // Contagem aproximada no raio, não total da arena nem garantia
                // de que todos estão atacando o jogador.
                contagem_parcial = true,
            };
        }

        private static bool IsEmily(GameObject go) =>
            go.name.IndexOf("Emily", StringComparison.OrdinalIgnoreCase) >= 0;

        private static bool IsPlayerSource(GameObject go)
        {
            var hero = HeroController.instance;
            return hero != null && (go == hero.gameObject ||
                go.transform.IsChildOf(hero.transform) ||
                go.name.IndexOf("Knight", StringComparison.OrdinalIgnoreCase) >= 0 &&
                go.GetComponent<DamageEnemies>() != null);
        }

        private static string Label(GameObject go)
        {
            if (go == null) return "";
            var name = (go.name ?? "").Replace("(Clone)", "").Trim();
            return name.Length > 70 ? name.Substring(0, 70) : name;
        }

        public void Reset()
        {
            _recentTargets.Clear();
            _lastTarget = _source = "";
            _lastTargetAt = _sourceAt = _nextScan = 0f;
            _sourceConfirmed = false;
            _sourceKind = "desconhecida";
            _nearby = 0;
            _nearbyNames.Clear();
        }

        public void Dispose()
        {
            On.HealthManager.Hit -= EnemyHit;
            On.HeroController.TakeDamage -= HeroDamage;
            Reset();
        }
    }
}