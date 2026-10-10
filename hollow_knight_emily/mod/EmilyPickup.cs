using UnityEngine;

namespace EmilyCompanion
{
    internal sealed class EmilyPickup : MonoBehaviour
    {
        public EmilyCompanionMod Mod;
        private Transform _hero;
        private float _bornAt;

        public static EmilyPickup Create(EmilyCompanionMod mod, Vector3 position)
        {
            var root = new GameObject("Coração do Vínculo");
            root.transform.position = position;
            var pickup = root.AddComponent<EmilyPickup>();
            pickup.Mod = mod;
            pickup._bornAt = Time.time;
            EmilyArt.Part(root.transform, "Core", Vector3.zero, new Vector3(.75f, .75f, 1), new Color(.92f, .5f, 1f), 40, 45);
            EmilyArt.Part(root.transform, "Halo", Vector3.zero, new Vector3(1.1f, .12f, 1), new Color(1f, .75f, 1f, .65f), 39);
            return pickup;
        }

        private void Update()
        {
            if (_hero == null && HeroController.instance != null) _hero = HeroController.instance.transform;
            transform.Rotate(0, 0, 45f * Time.deltaTime);
            transform.localScale = Vector3.one * (1f + Mathf.Sin(Time.time * 3f) * .08f);
            if (_hero != null && Time.time - _bornAt > .8f && Vector2.Distance(transform.position, _hero.position) < 1.5f)
            {
                Mod.AcquireEmily();
                Destroy(gameObject);
            }
        }
    }
}