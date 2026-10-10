package com.emily.music.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.unit.dp

// Tema escuro da Emily, com a paleta da interface web do PC (web/estilo.css).
// A Emily é sempre escura — dynamicColor (Material You) fica de fora de
// propósito pra o app não “trocar de cor” conforme o papel de parede.
private val EsquemaEscuro = darkColorScheme(
    primary = Acento,
    onPrimary = Texto,
    primaryContainer = BgAtivo,
    secondary = AcentoClaro,
    background = BgFundo,
    onBackground = Texto,
    surface = BgElevado,
    onSurface = Texto,
    surfaceVariant = BgHover,
    onSurfaceVariant = Texto2,
    outline = Linha,
    outlineVariant = Linha,
    error = Erro,
    onError = Texto
)

private val EsquemaClaro = EsquemaEscuro  // a Emily é sempre escura

// Escala de cantos igual à interface do PC: controles compactos têm 6–10px,
// painéis e diálogos sobem para 14–18px. Isso também alcança componentes M3
// que não definem shape localmente (menus, campos, botões e folhas).
private val FormasEmily = Shapes(
    extraSmall = RoundedCornerShape(6.dp),
    small = RoundedCornerShape(8.dp),
    medium = RoundedCornerShape(10.dp),
    large = RoundedCornerShape(14.dp),
    extraLarge = RoundedCornerShape(18.dp)
)

@Composable
fun EmilyAPPTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    dynamicColor: Boolean = false,
    content: @Composable () -> Unit
) {
    MaterialTheme(
        colorScheme = EsquemaEscuro,
        shapes = FormasEmily,
        content = content
    )
}
