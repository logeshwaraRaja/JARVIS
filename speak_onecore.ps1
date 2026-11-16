<#
    Speaks text read from stdin using Windows' newer "Natural" voices -- the ones under
    Settings -> Time & Language -> Speech (e.g. Aria, Guy, Jenny) -- via the OneCore/WinRT
    Windows.Media.SpeechSynthesis API. This is a different API from speak.ps1's classic SAPI5
    (System.Speech), which is why it needs its own script; invoked by tts.py the same way
    (subprocess, stdin pipe, kill the process to stop mid-sentence).

    Requires at least one Natural voice installed (Settings -> Time & Language -> Speech ->
    "Manage voices" -> Add voices) and a desktop Windows 10/11 build -- Server SKUs typically
    don't ship these. Falls back to the default voice if -VoiceSub matches nothing.

    Params:
      -VoiceSub  substring of a voice DisplayName (see `list_voices.py --onecore`); "" = default voice
#>
param(
    [string]$VoiceSub = ""
)

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.SpeechSynthesis.SpeechSynthesizer,Windows.Media.SpeechSynthesis,ContentType=WindowsRuntime]
$null = [Windows.Media.Core.MediaSource,Windows.Media.Core,ContentType=WindowsRuntime]
$null = [Windows.Media.Playback.MediaPlayer,Windows.Media.Playback,ContentType=WindowsRuntime]

# PowerShell can't `await` a WinRT IAsyncOperation directly -- this is the standard bridge:
# project it to a .NET Task via WindowsRuntimeSystemExtensions.AsTask<T>, then block on that.
function Wait-WinRT($Operation, [Type]$ResultType) {
    $asTaskGeneric = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1
    } | Select-Object -First 1
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $task = $asTask.Invoke($null, @($Operation))
    $task.Wait(-1) | Out-Null
    return $task.Result
}

$synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer

if ($VoiceSub -ne "") {
    $match = $synth.AllVoices | Where-Object { $_.DisplayName -like "*$VoiceSub*" } | Select-Object -First 1
    if ($match) {
        $synth.Voice = $match
    } else {
        Write-Error "No OneCore voice matches '*$VoiceSub*' -- using the default voice. Run 'list_voices.py --onecore' to see what's installed."
    }
}

$text = [Console]::In.ReadToEnd()
if (-not ($text -and $text.Trim().Length -gt 0)) { exit }

$stream = Wait-WinRT ($synth.SynthesizeTextToStreamAsync($text)) ([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])

$player = New-Object Windows.Media.Playback.MediaPlayer
$player.AutoPlay = $true
$player.Source = [Windows.Media.Core.MediaSource]::CreateFromStream($stream, $stream.ContentType)

# No easy blocking "wait for playback to finish" in PowerShell for MediaPlayer, so just sleep for
# the synthesized clip's own reported duration (plus a cushion) -- simpler and more robust here
# than polling PlaybackState or wiring up a WinRT event handler for one-shot playback.
$ms = [int]$stream.Duration.TotalMilliseconds
if ($ms -le 0) { $ms = [Math]::Max(500, $text.Length * 60) }   # safety fallback if Duration wasn't reported
Start-Sleep -Milliseconds ($ms + 400)
