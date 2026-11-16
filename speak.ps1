<#
    Speaks text read from stdin using Windows' built-in SAPI5 voices.
    Invoked by tts.py (subprocess, stdin pipe) -- not meant to be run by hand, though you can:
        "Hello there" | .\speak.ps1
    Params:
      -Rate     SAPI rate, -10 (slowest) .. 10 (fastest), 0 = normal
      -VoiceSub substring of a voice Name (see list_voices.py); omit/empty = Windows default voice
#>
param(
    [int]$Rate = 0,
    [string]$VoiceSub = ""
)

Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer

if ($VoiceSub -ne "") {
    $match = $synth.GetInstalledVoices() | Where-Object {
        $_.Enabled -and $_.VoiceInfo.Name -like "*$VoiceSub*"
    } | Select-Object -First 1
    if ($match) {
        $synth.SelectVoice($match.VoiceInfo.Name)
    } else {
        Write-Error "No installed voice matches '*$VoiceSub*' -- using the default voice instead. Run list_voices.py to see what's installed."
    }
}

$synth.Rate = $Rate

$text = [Console]::In.ReadToEnd()
if ($text -and $text.Trim().Length -gt 0) {
    $synth.Speak($text)
}
