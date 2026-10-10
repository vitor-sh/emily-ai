using SFCore;
using UnityEngine;

namespace EmilyCompanion
{
    public sealed class EmilyCharm : EasyCharm
    {
        protected override Sprite GetSpriteInternal() => EmilyArt.CreateCharmSprite();
        protected override string GetName() => "Vínculo de Emily";
        protected override string GetDescription() =>
            "Um pequeno coração violeta que pulsa com uma presença teimosa. " +
            "Invoca Emily, uma fada-mariposa protetora. Não ocupa encaixes.";
        protected override int GetCharmCost() => 0;
    }
}