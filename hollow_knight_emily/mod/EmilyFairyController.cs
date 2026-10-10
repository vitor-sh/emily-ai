using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace EmilyCompanion
{
    internal sealed class EmilyFairyController : MonoBehaviour
    {
        private const float SparkRange = 6.5f;
        private const float SupportCombatRange = 9f;
        private const float MarkRange = 10f;
        private Transform _hero;
        private const float AnimationFramesPerSecond = 12f;
        private SpriteRenderer _visual;
        private Sprite[] _activeFrames;
        private Sprite[] _benchFrames;
        private float _sparkAt, _soulAt, _pulseAt, _markAt, _shieldUntil, _lastScoldAt;
        private HealthManager _marked;
        private string _emotion = "neutra";
        public EmilyCompanionMod Mod;

        public static EmilyFairyController Create(EmilyCompanionMod mod)
        {
            var root = new GameObject("Emily Fairy Companion");
            DontDestroyOnLoad(root);
            var controller = root.AddComponent<EmilyFairyController>();
            controller.Mod = mod;
            controller.BuildBody();
            return controller;
        }

        private void BuildBody()
        {
            _activeFrames = EmilyArt.CreateActiveSprites();
            _benchFrames = EmilyArt.CreateBenchSprites();
            var visual = new GameObject("Emily Final Art");
            visual.transform.SetParent(transform, false);
            _visual = visual.AddComponent<SpriteRenderer>();
            _visual.sprite = _activeFrames[0];
            _visual.color = Color.white;
            _visual.sortingOrder = 55;
            transform.localScale = Vector3.one;
        }

        private void Update()
        {
            var heroController = HeroController.instance;
            if (_hero == null && heroController != null) _hero = heroController.transform;
            if (_hero == null) return;
            var right = heroController != null && heroController.cState.facingRight;
            var atBench = PlayerData.instance != null && PlayerData.instance.atBench;
            var hover = atBench ? .12f : .25f;
            var desired = _hero.position + new Vector3(
                right ? -2.2f : 2.2f,
                1.9f + Mathf.Sin(Time.time * 2.1f) * hover,
                -.4f);
            transform.position = Vector3.Lerp(transform.position, desired, 1f - Mathf.Exp(-5.5f * Time.deltaTime));
            var frames = atBench ? _benchFrames : _activeFrames;
            var frame = Mathf.FloorToInt(Time.time * AnimationFramesPerSecond) % frames.Length;
            _visual.sprite = frames[frame];
            _visual.flipX = !atBench && !right;
            AnimateVisual(atBench);
            _visual.color = EmotionTint();
            RunPowers();
        }

        private void AnimateVisual(bool atBench)
        {
            if (atBench)
            {
                _visual.transform.localPosition = Vector3.zero;
                _visual.transform.localRotation = Quaternion.identity;
                _visual.transform.localScale = Vector3.one;
                return;
            }

            var flutter = Mathf.Sin(Time.time * 9.5f);
            _visual.transform.localPosition = new Vector3(
                Mathf.Sin(Time.time * 4.1f) * .025f,
                Mathf.Sin(Time.time * 6.2f + .4f) * .035f,
                0f);
            _visual.transform.localRotation = Quaternion.Euler(
                0f, 0f, Mathf.Sin(Time.time * 2.7f + .6f) * 1.15f);
            _visual.transform.localScale = new Vector3(
                1f + flutter * .012f,
                1f - flutter * .008f,
                1f);
        }

        private Color EmotionTint()
        {
            var pulse = (Mathf.Sin(Time.time * 4f) + 1f) * .5f;
            if (_emotion == "assustada") return Color.Lerp(Color.white, new Color(1f, .84f, .94f), .12f + pulse * .08f);
            if (_emotion == "preocupada") return Color.Lerp(Color.white, new Color(.9f, .88f, 1f), .08f + pulse * .05f);
            return Color.white;
        }

        private void RunPowers()
        {
            if (!Mod.Active || GameManager.instance == null || GameManager.instance.isPaused) return;
            var hero = HeroController.instance;
            var pd = PlayerData.instance;
            if (hero == null || pd == null) return;
            var sparkReady = Mod.AutomaticAttacksEnabled && Time.time >= _sparkAt;
            var soulReady = Mod.SupportPowersEnabled && pd.MPCharge <= pd.maxMP / 3 && Time.time >= _soulAt;
            if (!sparkReady && !soulReady) return;
            var enemies = NearbyEnemies(soulReady ? SupportCombatRange : SparkRange);
            var sparkEnemies = enemies.Where(e =>
                Vector2.Distance(hero.transform.position, e.transform.position) <= SparkRange).ToList();
            if (sparkEnemies.Count > 0 && sparkReady)
            {
                _sparkAt = Time.time + 2.8f;
                var target = _marked != null && sparkEnemies.Contains(_marked) ? _marked :
                    sparkEnemies.OrderBy(e => Vector2.Distance(transform.position, e.transform.position)).First();
                Hit(target, Mathf.Max(2, pd.nailDamage / 4));
                Mod.OnPower("faisca_teimosa", target.gameObject.name, true);
            }
            if (enemies.Count > 0 && soulReady)
            {
                _soulAt = Time.time + 22f;
                hero.AddMPCharge(8);
                Mod.OnPower("eco_de_alma", "8", true);
            }
        }

        private static List<HealthManager> NearbyEnemies(float radius)
        {
            var hero = HeroController.instance;
            if (hero == null) return new List<HealthManager>();
            return FindObjectsOfType<HealthManager>()
                .Where(h => h != null && h.gameObject.activeInHierarchy && !h.GetIsDead() && h.hp > 0 &&
                            Vector2.Distance(hero.transform.position, h.transform.position) <= radius)
                .ToList();
        }

        private void Hit(HealthManager target, int damage)
        {
            if (target == null) return;
            target.Hit(new HitInstance {
                Source = gameObject, AttackType = AttackTypes.Spell, DamageDealt = damage,
                Direction = 0, MagnitudeMultiplier = .2f, MoveAngle = 0,
                MoveDirection = false, Multiplier = 1f, IgnoreInvulnerable = false,
                CircleDirection = false, SpecialType = SpecialTypes.None, IsExtraDamage = true
            });
        }

        public int ModifyIncomingDamage(int damage)
        {
            if (!Mod.Active || !Mod.SupportPowersEnabled || damage <= 0) return damage;
            var health = PlayerData.instance != null ? PlayerData.instance.health : 9;
            if (health - damage <= 0 && Time.time >= _shieldUntil)
            {
                _shieldUntil = Time.time + 75f;
                Mod.OnPower("escudo_da_filha", "fatal");
                SetEmotion("assustada");
                return 0;
            }
            return damage;
        }

        public void OnPlayerDamaged(int projectedHealth)
        {
            if (projectedHealth <= 2) SetEmotion("preocupada");
        }

        public void MarkNearest()
        {
            if (!Mod.OffensivePowersEnabled || Time.time < _markAt) return;
            var list = NearbyEnemies(MarkRange);
            if (list.Count == 0) return;
            _markAt = Time.time + 12f;
            _marked = list.OrderByDescending(h => h.hp).First();
            var renderer = _marked.GetComponent<SpriteRenderer>();
            if (renderer != null) renderer.color = Color.Lerp(renderer.color, new Color(1f, .5f, .9f), .55f);
            Mod.OnPower("marca_de_caca", _marked.gameObject.name);
        }

        public void PulseBond()
        {
            if (Time.time < _pulseAt || !Mod.Active || !Mod.OffensivePowersEnabled) return;
            _pulseAt = Time.time + 45f;
            foreach (var enemy in NearbyEnemies(8f)) Hit(enemy, Mathf.Max(4, PlayerData.instance.nailDamage / 2));
            if (PlayerData.instance.health < PlayerData.instance.maxHealth) HeroController.instance.AddHealth(1);
            Mod.OnPower("pulso_do_vinculo", "area");
        }

        public void LastScold()
        {
            if (!Mod.Active || !Mod.OffensivePowersEnabled || Time.time - _lastScoldAt < 3f) return;
            _lastScoldAt = Time.time;
            foreach (var enemy in NearbyEnemies(7f)) Hit(enemy, Mathf.Max(8, PlayerData.instance.nailDamage));
            Mod.OnPower("ultima_bronca", "morte");
        }

        public void SetEmotion(string emotion) => _emotion = emotion ?? "neutra";
        public string CooldownSummary() =>
            $"Faísca {Mathf.Max(0, _sparkAt-Time.time):0}s  " +
            $"Marca {Mathf.Max(0, _markAt-Time.time):0}s  " +
            $"Pulso {Mathf.Max(0, _pulseAt-Time.time):0}s";
    }
}