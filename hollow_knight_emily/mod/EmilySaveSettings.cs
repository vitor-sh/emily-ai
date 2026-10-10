using System.Collections.Generic;
using SFCore;

namespace EmilyCompanion
{
    public sealed class EmilySaveSettings
    {
        public bool EncontrouEmily;
        public bool AutoEquipou;
        public int Vinculo;
        public int InimigosAjudados;
        public int MortesPresenciadas;
        public List<string> BancosConhecidos = new List<string>();
        public EasyCharmState Charm = new EasyCharmState();
    }
}