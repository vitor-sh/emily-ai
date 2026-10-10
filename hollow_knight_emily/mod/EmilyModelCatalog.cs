using System;
using System.Collections.Generic;
using System.IO;
using Newtonsoft.Json;

namespace EmilyCompanion
{
    internal sealed class EmilyModelCatalog
    {
        private sealed class CatalogFile
        {
            public string padrao { get; set; }
            public List<CatalogModel> modelos { get; set; }
        }

        private sealed class CatalogModel
        {
            public string id { get; set; }
            public string nome { get; set; }
        }

        public readonly List<string> Ids = new List<string> { "" };
        public readonly List<string> Names = new List<string> { "Padrão da Emily" };

        public static EmilyModelCatalog Load()
        {
            var result = new EmilyModelCatalog();
            try
            {
                var dir = Path.GetDirectoryName(typeof(EmilyCompanionMod).Assembly.Location) ?? "";
                var path = Path.Combine(dir, "emily-hk-modelos.json");
                if (!File.Exists(path)) return result;
                var file = JsonConvert.DeserializeObject<CatalogFile>(File.ReadAllText(path));
                if (file?.modelos == null) return result;
                var defaultModel = file.modelos.Find(model => model != null && model.id == file.padrao);
                if (defaultModel != null)
                    result.Names[0] = "Padrão da Emily (" +
                        (string.IsNullOrWhiteSpace(defaultModel.nome) ? defaultModel.id : defaultModel.nome.Trim()) + ")";
                foreach (var model in file.modelos)
                {
                    var id = (model?.id ?? "").Trim();
                    if (string.IsNullOrEmpty(id) || result.Ids.Contains(id)) continue;
                    result.Ids.Add(id);
                    result.Names.Add(string.IsNullOrWhiteSpace(model.nome) ? id : model.nome.Trim());
                }
            }
            catch (Exception e)
            {
                Modding.Logger.LogWarn("Emily Companion não conseguiu ler o catálogo de modelos: " + e.Message);
            }
            return result;
        }

        public int IndexOf(string id)
        {
            var index = Ids.IndexOf(id ?? "");
            return index >= 0 ? index : 0;
        }
    }
}