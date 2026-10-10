namespace EmilyCompanion
{
    public sealed class EmilyGlobalSettings
    {
        public string ModoFala = "normal";
        public string Modelo = "";
        public bool IntegracaoIa = true;
        public bool Voz = true;
        public int Volume = 90;
        public bool Legendas = true;
        public string Hud = "vinculo";
        public bool AtaquesAutomaticos = true;
        public bool PoderesOfensivos = true;
        public bool PoderesSuporte = true;
        public bool SugestoesIa = true;
        public bool AutoEquipar = true;
        public string Ducking = "leve";

        public void Normalize()
        {
            if (ModoFala != "muda" && ModoFala != "quieta" && ModoFala != "normal" && ModoFala != "tagarela")
                ModoFala = "normal";
            if (Hud != "oculto" && Hud != "vinculo" && Hud != "detalhado") Hud = "vinculo";
            if (Ducking != "desligado" && Ducking != "leve" && Ducking != "forte") Ducking = "leve";
            if (Modelo == null) Modelo = "";
            Volume = System.Math.Max(0, System.Math.Min(200, Volume));
        }
    }
}