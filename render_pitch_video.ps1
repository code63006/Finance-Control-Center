param(
    [string]$OutputPath = "outputs\ai-finance-controller-pitch.mp4"
)

$ErrorActionPreference = "Stop"
$ffmpeg = "C:\Users\Ruturaj Khandale\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-full_build\bin\ffmpeg.exe"
if (-not (Test-Path $ffmpeg)) { throw "FFmpeg was not found at the expected local install path." }

$work = Join-Path $PSScriptRoot "outputs\pitch-video-work"
New-Item -ItemType Directory -Force -Path $work | Out-Null
Add-Type -AssemblyName System.Speech
Add-Type -AssemblyName System.Drawing

$scenes = @(
    @{ title="AI Finance Controller"; kicker="RECONCILIATION THAT KNOWS WHEN TO HOLD"; points=@("Run the books and cash position across gateway, settlement, bank, refund, and ledger data.", "Detect the exceptions that matter. Explain the evidence. Recommend the safe next action."); narration="Every finance team faces the same close problem. Payments are captured in the gateway, settlements arrive later, bank credits arrive separately, refunds change the expected cash position, and the ledger still has to balance. Today, that work happens across spreadsheets and manual follow-ups. AI Finance Controller is a finance operations control layer. It reconciles the lifecycle, identifies cash exceptions, explains the evidence, and tells the team what to do next. It does not move money. It makes the close faster, clearer, and safer." },
    @{ title="The control gap"; kicker="WHY RECONCILIATION BREAKS"; points=@("One payment can appear in five different systems at different times.", "A missing bank receipt can be a delay, an ingestion gap, a wrong settlement, or a true cash shortfall.", "A good controller must abstain when evidence is incomplete."); narration="The difficult part is not generating an answer. The difficult part is verifying the money. One payment can show up in several systems, with different timestamps, identifiers, and settlement amounts. When bank cash is missing, the team must distinguish between a delayed settlement, an incomplete data feed, a mismatch, and a genuine shortfall. A reliable system cannot simply guess. It must show the evidence, show what is missing, and route uncertain cases to human review." },
    @{ title="Five source views, one lifecycle"; kicker="LOCAL DEMO INPUTS"; points=@("Payment gateway export", "Settlement report", "Bank statement CSV", "Refund export", "ERP or ledger export"); narration="The controller accepts the source views finance teams already use: payment gateway transactions, settlement reports, bank statement CSV files, refund exports, and ERP or ledger postings. Every record is normalized and validated before reconciliation. The system retains lineage from the source record into the exception investigation, so the reviewer can see where a financial fact came from rather than relying on a black-box answer." },
    @{ title="Control room"; kicker="LIVE BATCH SUMMARY"; points=@("60 live demonstration cases and 626 validated source records", "Cash exposure and pending settlement are shown before the team opens a spreadsheet.", "Linked cases, exceptions, and clean-case integrity are measured separately."); narration="This is the control room. It processes a live demonstration batch of 60 cases and 626 source records. The top view shows cash exposure, pending settlement, cases that need review, and diagnosis coverage. Importantly, it separates clean-case integrity from detected exceptions. That prevents an exception queue from being misrepresented as a system failure. The team sees what reconciled, what needs evidence, and where financial risk is concentrated." },
    @{ title="Critical exception: Rs 8.30 lakh at risk"; kicker="FLAGSHIP SETTLEMENT CASE"; points=@("Payment captured: Rs 8,50,000", "Expected settlement: Rs 8,29,940", "Bank receipt: Rs 0", "Decision: HOLD"); narration="Here is the highest-impact exception. A card payment of eight lakh fifty thousand rupees was captured. After platform fees and GST, the expected merchant settlement is eight lakh twenty-nine thousand nine hundred forty rupees. But the bank receipt is zero. The controller places this case at the top of the queue as critical. It does not post a compensating entry. Its recommendation is simple: hold booking and request settlement advice." },
    @{ title="Evidence before action"; kicker="CASE INVESTIGATION"; points=@("Leading cause: amount drift or missing bank receipt", "Supporting evidence: fee and tax records exist; source timing is valid; amounts differ.", "Missing evidence: bank statement line and processor settlement advice.", "Competing causes remain visible instead of being hidden."); narration="The investigation panel answers the questions a finance reviewer needs answered. What was expected? What actually happened? What evidence supports the leading cause? What other explanation is still possible? And what document is required before a decision? In this case, the fee record exists, the tax record exists, source timing is valid, and the expected settlement has no matching bank receipt. The system shows the missing bank line and settlement advice as the evidence gap. That is why the decision is hold, not book." },
    @{ title="A safe, grounded copilot"; kicker="ASK: WHY IS THIS SETTLEMENT BLOCKED?"; points=@("Direct answer", "Evidence used", "Confidence and caveat", "Safe next step", "Book / Hold / Escalate recommendation"); narration="The copilot is intentionally constrained. It never invents a financial number, and it never changes a financial record. When asked why this settlement is blocked, it retrieves the reconciled state for the selected case. It states the expected settlement, the bank receipt, the variance, and the evidence. It returns a confidence level and caveat. For this case, the caveat is that settlement advice is still required. Its decision is hold, and its next step is to request the bank statement line and processor settlement advice." },
    @{ title="Measured on unseen data"; kicker="BENCHMARK QUALITY"; points=@("120-case unseen holdout", "1,241 holdout source records", "At least 10 examples for every anomaly class", "97.5% top-1 accuracy / 97.5% macro-F1", "31.7% abstention rate / 3 retained miss analyses"); narration="This is not based on one selected example. The system is tested on a separate 120-case unseen holdout with 1,241 source records. Every anomaly class has at least ten examples. The benchmark reports per-class precision, recall, F1, top-one accuracy, macro F1, and abstention rate. The current holdout result is 97.5 percent top-one accuracy and 97.5 percent macro F1. The controller abstains in 31.7 percent of cases when the evidence is not enough. Every miss is retained with its predicted cause, actual cause, outcome, and evidence gap." },
    @{ title="The finance workflow"; kicker="HUMAN CONTROL STAYS IN THE LOOP"; points=@("1. Load and validate source files", "2. Review close status and cash exposure", "3. Open the highest-impact exception", "4. Inspect evidence and missing documents", "5. Ask the copilot", "6. Book, hold, or escalate - demo workflow only"); narration="The daily workflow is straightforward. Load and validate the source files. Review the close status and cash exposure. Open the highest-impact exception. Inspect the source timeline, evidence, competing causes, and missing documents. Ask the copilot for an evidence-backed explanation. Then the finance owner chooses to book, hold, or escalate. In this prototype those actions are explicitly demo workflow state. In production they would connect to controlled approvals and audit trails, not automatically move money." },
    @{ title="Close faster. Act safer."; kicker="AI FINANCE CONTROLLER"; points=@("Reconcile the full money lifecycle.", "Find the cash exceptions that matter.", "Explain evidence, uncertainty, and next action.", "Keep people in control of every financial decision."); narration="AI Finance Controller turns reconciliation from a spreadsheet chase into an auditable operating workflow. It reconciles the money lifecycle, finds the cash exceptions that matter, explains the evidence, and gives the finance team a safe next action. It does not replace financial controls. It strengthens them. The result is a faster close, clearer accountability, and safer decisions when cash is at risk." }
)

function New-Slide([hashtable]$scene, [string]$path) {
    $bitmap = New-Object System.Drawing.Bitmap 1920,1080
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
    $navy = [System.Drawing.Color]::FromArgb(24,50,74)
    $paper = [System.Drawing.Color]::FromArgb(245,247,246)
    $mint = [System.Drawing.Color]::FromArgb(28,140,120)
    $amber = [System.Drawing.Color]::FromArgb(217,144,37)
    $ink = [System.Drawing.Color]::FromArgb(23,33,43)
    $muted = [System.Drawing.Color]::FromArgb(104,117,128)
    $graphics.Clear($paper)
    $graphics.FillRectangle((New-Object System.Drawing.SolidBrush $navy), 0, 0, 1920, 190)
    $graphics.FillRectangle((New-Object System.Drawing.SolidBrush $amber), 90, 270, 10, 630)
    $brandFont = New-Object System.Drawing.Font('Georgia', 36, [System.Drawing.FontStyle]::Bold)
    $titleFont = New-Object System.Drawing.Font('Georgia', 54, [System.Drawing.FontStyle]::Bold)
    $kickerFont = New-Object System.Drawing.Font('Segoe UI', 20, [System.Drawing.FontStyle]::Bold)
    $pointFont = New-Object System.Drawing.Font('Segoe UI', 31, [System.Drawing.FontStyle]::Regular)
    $footerFont = New-Object System.Drawing.Font('Segoe UI', 18, [System.Drawing.FontStyle]::Regular)
    $graphics.DrawString('Finance Control Center', $brandFont, [System.Drawing.Brushes]::White, 90, 62)
    $graphics.DrawString($scene.kicker, $kickerFont, (New-Object System.Drawing.SolidBrush $mint), 115, 285)
    $graphics.DrawString($scene.title, $titleFont, (New-Object System.Drawing.SolidBrush $ink), 115, 330)
    $y = 470
    foreach ($point in $scene.points) {
        $graphics.FillEllipse((New-Object System.Drawing.SolidBrush $mint), 122, ($y + 12), 15, 15)
        $rect = New-Object System.Drawing.RectangleF(160, $y, 1560, 110)
        $graphics.DrawString($point, $pointFont, (New-Object System.Drawing.SolidBrush $ink), $rect)
        $y += 120
    }
    $graphics.DrawString('Synthetic benchmark demo / Financial actions are demo workflow state only', $footerFont, (New-Object System.Drawing.SolidBrush $muted), 90, 1015)
    $bitmap.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    $graphics.Dispose(); $bitmap.Dispose()
}

$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voice.Rate = -1
$segments = @()
for ($i = 0; $i -lt $scenes.Count; $i++) {
    $index = '{0:D2}' -f ($i + 1)
    $image = Join-Path $work "slide-$index.png"
    $audio = Join-Path $work "voice-$index.wav"
    $segment = Join-Path $work "segment-$index.mp4"
    New-Slide $scenes[$i] $image
    $voice.SetOutputToWaveFile($audio)
    $voice.Speak($scenes[$i].narration)
    $voice.SetOutputToDefaultAudioDevice()
    & $ffmpeg -y -loop 1 -i $image -i $audio -c:v libx264 -tune stillimage -c:a aac -b:a 192k -pix_fmt yuv420p -shortest -r 30 $segment | Out-Null
    $segments += $segment
}
$voice.Dispose()
$concat = Join-Path $work "concat.txt"
$segments | ForEach-Object { "file '$($_.Replace('\','/'))'" } | Set-Content -Encoding ascii $concat
& $ffmpeg -y -f concat -safe 0 -i $concat -c copy $OutputPath | Out-Null
Write-Output "Video created: $OutputPath"
