namespace EmilyCompanion
{
    /// <summary>
    /// Uma fala pronta para ser dita. O mod mantém a ordem por Sequence e só
    /// começa uma fala nova quando a anterior terminou.
    /// </summary>
    internal sealed class EmilySpeechItem
    {
        public int Sequence;
        public string Text = "";
        public string Emotion = "neutra";
        public string Suggested = "nenhuma";
        public string Zone = "";
        public bool ValidateZone;
        public bool Persistent;
        public bool VoiceExpected;
        public bool VoiceResolved;
        public byte[] Wav;
        public EmilyPcmStream PcmStream;
    }
}