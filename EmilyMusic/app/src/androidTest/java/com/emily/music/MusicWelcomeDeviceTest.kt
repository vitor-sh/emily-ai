package com.emily.music
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
class MusicWelcomeDeviceTest {
    @get:Rule val compose=createComposeRule()
    @Test fun welcomeIsIndependentOfEmily() {
        var entered=false;var closed=false
        compose.setContent {MusicWelcomeScreen(false,false,null,{entered=true},{},{closed=true})}
        compose.onNodeWithText("Emily Music").assertIsDisplayed()
        compose.onNodeWithText("Entrar com Google").performScrollTo().performClick()
        compose.onNodeWithText("Fechar").performScrollTo().performClick()
        compose.runOnIdle {assertTrue(entered);assertTrue(closed)}
    }
}
