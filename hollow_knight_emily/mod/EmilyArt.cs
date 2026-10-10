using System;
using System.IO;
using System.Reflection;
using UnityEngine;

namespace EmilyCompanion
{
    internal static class EmilyArt
    {
        private static Sprite _white;
        private static Sprite _charm;
        private static Texture2D _activeTexture;
        private static Texture2D _benchTexture;
        private static Texture2D _charmTexture;
        private static Sprite[] _activeFrames;
        private static Sprite[] _benchFrames;

        private const int FrameCount = 24;
        private const int Columns = 4;
        private const int ActiveCellWidth = 216;
        private const int ActiveCellHeight = 192;
        private const int BenchCellWidth = 240;
        private const int BenchCellHeight = 168;
        private const float EmilyPixelsPerUnit = 180f;

        public static Sprite WhiteSprite()
        {
            if (_white != null) return _white;
            var texture = new Texture2D(16, 16, TextureFormat.ARGB32, false);
            texture.name = "Emily Procedural White";
            var pixels = new Color[256];
            for (var i = 0; i < pixels.Length; i++) pixels[i] = Color.white;
            texture.SetPixels(pixels);
            texture.Apply();
            _white = Sprite.Create(texture, new Rect(0, 0, 16, 16), new Vector2(.5f, .5f), 16f);
            return _white;
        }

        public static Sprite CreateCharmSprite()
        {
            if (_charm != null) return _charm;
            _charmTexture = LoadEmbeddedTexture("EmilyCompanion.Assets.EmilyCharm.png", "Vínculo de Emily");
            _charm = Sprite.Create(_charmTexture,
                new Rect(0, 0, _charmTexture.width, _charmTexture.height),
                new Vector2(.5f, .5f), 128f, 0, SpriteMeshType.FullRect);
            _charm.name = "Vínculo de Emily";
            return _charm;
        }

        public static Sprite[] CreateActiveSprites()
        {
            if (_activeFrames != null) return _activeFrames;
            _activeTexture = LoadEmbeddedTexture(
                "EmilyCompanion.Assets.EmilyActive.png", "Emily Active Expectation");
            _activeFrames = CreateFrames(
                _activeTexture, ActiveCellWidth, ActiveCellHeight, "Emily Active");
            return _activeFrames;
        }

        public static Sprite[] CreateBenchSprites()
        {
            if (_benchFrames != null) return _benchFrames;
            _benchTexture = LoadEmbeddedTexture(
                "EmilyCompanion.Assets.EmilyBench.png", "Emily Bench Front");
            _benchFrames = CreateFrames(
                _benchTexture, BenchCellWidth, BenchCellHeight, "Emily Bench");
            return _benchFrames;
        }

        private static Sprite[] CreateFrames(Texture2D texture, int cellWidth,
            int cellHeight, string name)
        {
            var expectedWidth = cellWidth * Columns;
            var expectedRows = FrameCount / Columns;
            var expectedHeight = cellHeight * expectedRows;
            if (texture.width != expectedWidth || texture.height != expectedHeight)
                throw new InvalidOperationException(
                    $"Spritesheet {name} inválido: {texture.width}x{texture.height}; " +
                    $"esperado {expectedWidth}x{expectedHeight}.");

            var frames = new Sprite[FrameCount];
            for (var i = 0; i < FrameCount; i++)
            {
                var column = i % Columns;
                var rowFromTop = i / Columns;
                var y = texture.height - (rowFromTop + 1) * cellHeight;
                frames[i] = Sprite.Create(texture,
                    new Rect(column * cellWidth, y, cellWidth, cellHeight),
                    new Vector2(.5f, .5f), EmilyPixelsPerUnit, 0, SpriteMeshType.FullRect);
                frames[i].name = $"{name} {i:00}";
            }
            return frames;
        }

        private static Texture2D LoadEmbeddedTexture(string resourceName, string textureName)
        {
            var assembly = Assembly.GetExecutingAssembly();
            using (var stream = assembly.GetManifestResourceStream(resourceName))
            {
                if (stream == null)
                    throw new FileNotFoundException("Recurso visual embutido não encontrado.", resourceName);

                using (var memory = new MemoryStream())
                {
                    stream.CopyTo(memory);
                    var texture = new Texture2D(2, 2, TextureFormat.ARGB32, false);
                    texture.name = textureName;
                    texture.filterMode = FilterMode.Bilinear;
                    texture.wrapMode = TextureWrapMode.Clamp;
                    texture.anisoLevel = 0;
                    if (!texture.LoadImage(memory.ToArray(), false))
                    {
                        UnityEngine.Object.Destroy(texture);
                        throw new InvalidDataException("Falha ao decodificar o recurso visual " + resourceName);
                    }
                    return texture;
                }
            }
        }

        public static GameObject Part(Transform parent, string name, Vector3 localPosition,
            Vector3 scale, Color color, int order, float rotation = 0f)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            go.transform.localPosition = localPosition;
            go.transform.localScale = scale;
            go.transform.localRotation = Quaternion.Euler(0, 0, rotation);
            var renderer = go.AddComponent<SpriteRenderer>();
            renderer.sprite = WhiteSprite();
            renderer.color = color;
            renderer.sortingOrder = order;
            return go;
        }
    }
}