using System;
using System.Collections.Generic;

namespace EmilyCompanion
{
    /// <summary>
    /// Traduz a zona interna do mapa para o nome que a Emily usa ao falar.
    ///
    /// O mod manda as duas formas: a chave crua (telemetria e memória) e o nome
    /// legível, para o modelo nunca comentar "GREEN_PATH" nem confundir uma
    /// região com outra. Zona desconhecida devolve vazio em vez de inventar
    /// nome, porque lugar errado é pior do que lugar sem nome.
    /// </summary>
    internal static class EmilyLocations
    {
        private static readonly Dictionary<string, string> Nomes =
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            {
                { "KINGS_PASS", "Passo do Rei" },
                { "CLIFFS", "Penhascos Uivantes" },
                { "TOWN", "Boca do Rei" },
                { "CROSSROADS", "Encruzilhada Esquecida" },
                { "GREEN_PATH", "Caminho Verde" },
                { "ROYAL_GARDENS", "Jardins da Rainha" },
                { "FOG_CANYON", "Cânion da Névoa" },
                { "WASTES", "Ermos Fúngicos" },
                { "DEEPNEST", "Ninho Profundo" },
                { "HIVE", "Colmeia" },
                { "BONE_FOREST", "Floresta de Ossos" },
                { "PALACE_GROUNDS", "Terrenos do Palácio" },
                { "MINES", "Pico de Cristal" },
                { "RESTING_GROUNDS", "Terra do Descanso" },
                { "CITY", "Cidade das Lágrimas" },
                { "DREAM_WORLD", "Mundo dos Sonhos" },
                { "COLOSSEUM", "Coliseu dos Tolos" },
                { "ABYSS", "Abismo" },
                { "ROYAL_QUARTER", "Bairro Real" },
                { "WHITE_PALACE", "Palácio Branco" },
                { "SHAMAN_TEMPLE", "Templo do Xamã" },
                { "WATERWAYS", "Canais Reais" },
                { "QUEENS_STATION", "Estação da Rainha" },
                { "OUTSKIRTS", "Arredores" },
                { "KINGS_STATION", "Estação do Rei" },
                { "MAGE_TOWER", "Torre do Mago" },
                { "TRAM_UPPER", "Bonde Superior" },
                { "TRAM_LOWER", "Bonde Inferior" },
                { "SOUL_SOCIETY", "Sociedade das Almas" },
                { "ACID_LAKE", "Lago de Ácido" },
                { "NOEYES_TEMPLE", "Templo de Noeyes" },
                { "MONOMON_ARCHIVE", "Arquivo de Monomon" },
                { "MANTIS_VILLAGE", "Vila dos Louva-a-Deus" },
                { "RUINED_TRAMWAY", "Bonde em Ruínas" },
                { "DISTANT_VILLAGE", "Vila Distante" },
                { "ABYSS_DEEP", "Profundeza do Abismo" },
                { "ISMAS_GROVE", "Bosque de Isma" },
                { "WYRMSKIN", "Pele de Wyrm" },
                { "LURIENS_TOWER", "Torre de Lurien" },
                { "LOVE_TOWER", "Torre do Amor" },
                { "GLADE", "Clareira" },
                { "BLUE_LAKE", "Lago Azul" },
                { "PEAK", "Pico" },
                { "JONI_GRAVE", "Túmulo de Joni" },
                { "OVERGROWN_MOUND", "Monte Coberto" },
                { "CRYSTAL_MOUND", "Monte de Cristal" },
                { "BEASTS_DEN", "Covil das Feras" },
                { "GODS_GLORY", "Glória dos Deuses" },
                { "GODSEEKER_WASTE", "Ermo do Caçador de Deuses" },
            };

        public static string Nome(string zona)
        {
            if (string.IsNullOrWhiteSpace(zona)) return "";
            string nome;
            return Nomes.TryGetValue(zona.Trim(), out nome) ? nome : "";
        }

        public static string NomeDoMapZone()
        {
            var pd = PlayerData.instance;
            return pd == null ? "" : Nome(pd.mapZone.ToString());
        }
    }
}