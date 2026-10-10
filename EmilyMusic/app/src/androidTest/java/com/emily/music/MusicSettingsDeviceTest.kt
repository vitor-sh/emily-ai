package com.emily.music

import androidx.compose.runtime.*
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import com.emily.music.ui.theme.EmilyAPPTheme
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class MusicSettingsDeviceTest {
    @get:Rule val compose=createComposeRule()
    @Test fun accountActionsLiveInSettingsAndCannotRunTwiceWhileBusy() {
        var called=false
        compose.setContent {
            var busy by remember {mutableStateOf(false)}
            EmilyAPPTheme {MusicSettingsSheet("conta@exemplo.com",busy,null,{}, {called=true;busy=true})}
        }
        compose.onNodeWithText("Configurações").assertIsDisplayed()
        compose.onNodeWithText("conta@exemplo.com").assertIsDisplayed()
        compose.onNodeWithText("Sair da conta").performScrollTo().performClick()
        compose.onNodeWithText("Saindo…").assertIsNotEnabled()
        compose.runOnIdle{assertTrue(called)}
    }
}
