$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$outDir = Join-Path $root "docs"
$pptxPath = Join-Path $outDir "strategy_beginner_guide.pptx"
$pdfPath = Join-Path $outDir "strategy_beginner_guide.pdf"

if (-not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Path $outDir | Out-Null
}

if (Test-Path $pptxPath) {
    Remove-Item -LiteralPath $pptxPath -Force
}
if (Test-Path $pdfPath) {
    Remove-Item -LiteralPath $pdfPath -Force
}

$slides = @(
    @{
        Title = "EMA + Bollinger Band + RSI"
        Subtitle = "초보자를 위한 자동매매 전략 설명"
        Bullets = @(
            "이 전략은 추세, 돌파, 힘을 동시에 확인합니다.",
            "상승 흐름이면 LONG, 하락 흐름이면 SHORT을 검토합니다.",
            "한 종목에서 동시에 롱/숏을 같이 들고 있지는 않습니다."
        )
        Note = "핵심 질문: 지금 시장이 어느 방향으로 힘 있게 움직이는가?"
    },
    @{
        Title = "전체 아이디어"
        Subtitle = "3개의 신호가 모두 맞아야 진입"
        Bullets = @(
            "EMA: 큰 방향을 확인합니다.",
            "볼린저밴드: 평소 범위를 벗어난 돌파를 확인합니다.",
            "RSI: 그 방향으로 실제 힘이 붙었는지 확인합니다.",
            "하나만 맞으면 기다리고, 세 가지가 모두 맞을 때만 진입합니다."
        )
        Note = "많이 매매하는 전략이 아니라 조건을 강하게 거르는 전략입니다."
    },
    @{
        Title = "1. EMA 추세"
        Subtitle = "EMA20과 EMA60으로 방향을 봅니다"
        Bullets = @(
            "EMA20은 최근 가격 변화에 더 민감합니다.",
            "EMA60은 더 긴 흐름을 보여줍니다.",
            "EMA20 > EMA60이면 상승 추세로 봅니다.",
            "EMA20 < EMA60이면 하락 추세로 봅니다."
        )
        Note = "EMA는 시장의 큰 방향을 거르는 첫 번째 필터입니다."
    },
    @{
        Title = "2. 볼린저밴드 돌파"
        Subtitle = "평소 움직임의 범위를 벗어났는지 확인"
        Bullets = @(
            "상단 밴드 돌파는 강한 상승 시도로 봅니다.",
            "하단 밴드 이탈은 강한 하락 시도로 봅니다.",
            "단순 상승/하락이 아니라 평소보다 강한 움직임인지 확인합니다."
        )
        Note = "돌파는 추세가 실제 가격 움직임으로 나타나는 순간을 찾는 장치입니다."
    },
    @{
        Title = "3. RSI 모멘텀"
        Subtitle = "가격 움직임에 힘이 있는지 확인"
        Bullets = @(
            "LONG은 RSI가 52보다 크고 직전보다 올라야 합니다.",
            "SHORT은 RSI가 48보다 작고 직전보다 내려야 합니다.",
            "RSI를 역추세 매매가 아니라 방향 확인용으로 씁니다."
        )
        Note = "RSI는 움직임이 힘 없이 튄 것인지, 실제로 밀고 가는 흐름인지 봅니다."
    },
    @{
        Title = "LONG 진입 기준"
        Subtitle = "상승 추세 + 상단 돌파 + 상승 모멘텀"
        Bullets = @(
            "EMA20 > EMA60",
            "종가가 직전 기준 볼린저밴드 상단보다 높음",
            "RSI > 52 그리고 RSI가 직전보다 상승",
            "세 조건이 모두 맞을 때만 LONG 신호가 발생합니다."
        )
        Note = "쉽게 말해 위쪽으로 가는 시장에서 강하게 위로 터질 때만 매수합니다."
    },
    @{
        Title = "SHORT 진입 기준"
        Subtitle = "하락 추세 + 하단 이탈 + 하락 모멘텀"
        Bullets = @(
            "EMA20 < EMA60",
            "종가가 직전 기준 볼린저밴드 하단보다 낮음",
            "RSI < 48 그리고 RSI가 직전보다 하락",
            "세 조건이 모두 맞을 때만 SHORT 신호가 발생합니다."
        )
        Note = "쉽게 말해 아래쪽으로 가는 시장에서 강하게 아래로 밀릴 때만 매도합니다."
    },
    @{
        Title = "리스크 관리"
        Subtitle = "진입보다 중요한 방어 규칙"
        Bullets = @(
            "1회 거래 손실 한도는 계좌의 0.5%입니다.",
            "손절폭은 ATR x 1.5로 계산합니다.",
            "익절폭은 손절폭의 1.8배입니다.",
            "하루 손실이 -3%에 도달하면 신규 진입을 멈춥니다."
        )
        Note = "전략이 틀릴 수 있다는 전제로 손실 크기를 먼저 제한합니다."
    },
    @{
        Title = "실행 흐름"
        Subtitle = "30초마다 감시, 15분봉 확정 때 판단"
        Bullets = @(
            "봇은 30초마다 BTC/ETH 상태를 확인합니다.",
            "새 15분봉이 확정됐을 때만 진입 신호를 계산합니다.",
            "진입하면 시장가 주문 후 손절/익절 예약주문을 함께 둡니다.",
            "손절/익절 체결은 다음 폴링에서 감지하고 알림을 보냅니다."
        )
        Note = "자주 감시하지만, 매매 판단은 캔들이 확정된 순간에만 합니다."
    },
    @{
        Title = "한 줄 요약"
        Subtitle = "방향, 돌파, 힘을 모두 확인하는 전략"
        Bullets = @(
            "EMA로 방향을 고릅니다.",
            "볼린저밴드로 강한 돌파를 확인합니다.",
            "RSI로 그 돌파에 힘이 있는지 확인합니다.",
            "ATR 기반 손절/익절로 위험을 제한합니다."
        )
        Note = "조건이 맞을 때만 들어가는 필터형 추세 돌파 전략입니다."
    }
)

function Add-TextBox {
    param(
        [object]$Slide,
        [string]$Text,
        [float]$Left,
        [float]$Top,
        [float]$Width,
        [float]$Height,
        [int]$FontSize,
        [int]$Color,
        [bool]$Bold = $false
    )
    $shape = $Slide.Shapes.AddTextbox(1, $Left, $Top, $Width, $Height)
    $shape.TextFrame.TextRange.Text = $Text
    $shape.TextFrame.TextRange.Font.Name = "맑은 고딕"
    $shape.TextFrame.TextRange.Font.Size = $FontSize
    $shape.TextFrame.TextRange.Font.Color.RGB = $Color
    if ($Bold) {
        $shape.TextFrame.TextRange.Font.Bold = -1
    }
    $shape.TextFrame.MarginLeft = 0
    $shape.TextFrame.MarginRight = 0
    $shape.TextFrame.MarginTop = 0
    $shape.TextFrame.MarginBottom = 0
    return $shape
}

function Add-BulletBox {
    param(
        [object]$Slide,
        [string[]]$Bullets,
        [float]$Left,
        [float]$Top,
        [float]$Width,
        [float]$Height
    )
    $text = ($Bullets | ForEach-Object { "• " + $_ }) -join "`r"
    $shape = Add-TextBox -Slide $Slide -Text $text -Left $Left -Top $Top -Width $Width -Height $Height -FontSize 20 -Color 0x1F2937
    $shape.TextFrame.TextRange.ParagraphFormat.SpaceAfter = 10
    return $shape
}

function Add-Chart {
    param([object]$Slide)
    $box = $Slide.Shapes.AddShape(1, 620, 165, 330, 235)
    $box.Fill.ForeColor.RGB = 0xF8FAFC
    $box.Line.ForeColor.RGB = 0xCBD5E1

    $upper = $Slide.Shapes.AddLine(650, 205, 920, 205)
    $upper.Line.ForeColor.RGB = 0x64748B
    $upper.Line.Weight = 1.5
    $mid = $Slide.Shapes.AddLine(650, 285, 920, 285)
    $mid.Line.ForeColor.RGB = 0xCBD5E1
    $mid.Line.Weight = 1
    $lower = $Slide.Shapes.AddLine(650, 365, 920, 365)
    $lower.Line.ForeColor.RGB = 0x64748B
    $lower.Line.Weight = 1.5

    $emaFast = $Slide.Shapes.AddLine(650, 345, 920, 230)
    $emaFast.Line.ForeColor.RGB = 0x2563EB
    $emaFast.Line.Weight = 3
    $emaSlow = $Slide.Shapes.AddLine(650, 365, 920, 285)
    $emaSlow.Line.ForeColor.RGB = 0xDC2626
    $emaSlow.Line.Weight = 3

    $points = @(
        @(665, 350, 710, 323),
        @(710, 323, 760, 345),
        @(760, 345, 815, 270),
        @(815, 270, 880, 218),
        @(880, 218, 925, 190)
    )
    foreach ($p in $points) {
        $line = $Slide.Shapes.AddLine($p[0], $p[1], $p[2], $p[3])
        $line.Line.ForeColor.RGB = 0x111827
        $line.Line.Weight = 3
    }

    Add-TextBox -Slide $Slide -Text "상단 밴드" -Left 653 -Top 180 -Width 120 -Height 20 -FontSize 11 -Color 0x64748B | Out-Null
    Add-TextBox -Slide $Slide -Text "하단 밴드" -Left 653 -Top 370 -Width 120 -Height 20 -FontSize 11 -Color 0x64748B | Out-Null
    Add-TextBox -Slide $Slide -Text "밴드 밖으로 강하게 움직이는 순간" -Left 640 -Top 430 -Width 300 -Height 34 -FontSize 15 -Color 0x111827 -Bold $true | Out-Null
}

function Add-FilterStack {
    param([object]$Slide)
    $labels = @("EMA 방향", "볼린저밴드 돌파", "RSI 힘 확인")
    $colors = @(0x2563EB, 0x059669, 0xDC2626)
    for ($i = 0; $i -lt $labels.Count; $i++) {
        $top = 185 + ($i * 82)
        $shape = $Slide.Shapes.AddShape(5, 660, $top, 245, 52)
        $shape.Fill.ForeColor.RGB = $colors[$i]
        $shape.Line.ForeColor.RGB = $colors[$i]
        Add-TextBox -Slide $Slide -Text $labels[$i] -Left 690 -Top ($top + 12) -Width 190 -Height 24 -FontSize 17 -Color 0xFFFFFF -Bold $true | Out-Null
        if ($i -lt 2) {
            $line = $Slide.Shapes.AddLine(782, $top + 56, 782, $top + 78)
            $line.Line.ForeColor.RGB = 0x64748B
            $line.Line.Weight = 2
        }
    }
}

$ppt = New-Object -ComObject PowerPoint.Application
$presentation = $ppt.Presentations.Add()
$presentation.PageSetup.SlideWidth = 960
$presentation.PageSetup.SlideHeight = 540

$accentColors = @(0x2563EB, 0x059669, 0xDC2626, 0x7C3AED)

for ($i = 0; $i -lt $slides.Count; $i++) {
    $data = $slides[$i]
    $slide = $presentation.Slides.Add($i + 1, 12)
    $accent = $accentColors[$i % $accentColors.Count]

    $bg = $slide.Shapes.AddShape(1, 0, 0, 960, 540)
    $bg.Fill.ForeColor.RGB = 0xFFFFFF
    $bg.Line.Visible = 0

    $bar = $slide.Shapes.AddShape(1, 0, 0, 960, 28)
    $bar.Fill.ForeColor.RGB = $accent
    $bar.Line.Visible = 0

    Add-TextBox -Slide $slide -Text $data.Title -Left 58 -Top 58 -Width 540 -Height 54 -FontSize 31 -Color 0x0F172A -Bold $true | Out-Null
    Add-TextBox -Slide $slide -Text $data.Subtitle -Left 60 -Top 114 -Width 540 -Height 30 -FontSize 17 -Color $accent -Bold $true | Out-Null
    Add-BulletBox -Slide $slide -Bullets $data.Bullets -Left 70 -Top 182 -Width 490 -Height 230 | Out-Null

    $note = $slide.Shapes.AddShape(5, 60, 448, 835, 52)
    $note.Fill.ForeColor.RGB = 0xE0F2FE
    $note.Line.ForeColor.RGB = 0xBAE6FD
    Add-TextBox -Slide $slide -Text $data.Note -Left 84 -Top 462 -Width 790 -Height 26 -FontSize 15 -Color 0x075985 -Bold $true | Out-Null

    Add-TextBox -Slide $slide -Text ([string]($i + 1)) -Left 910 -Top 505 -Width 30 -Height 16 -FontSize 10 -Color 0x64748B | Out-Null

    if (($i + 1) -in @(1, 2, 4, 6, 7, 10)) {
        Add-Chart -Slide $slide
    } else {
        Add-FilterStack -Slide $slide
    }
}

$presentation.SaveAs($pptxPath, 24)
$presentation.SaveAs($pdfPath, 32)
$presentation.Close()
$ppt.Quit()

Write-Host $pptxPath
Write-Host $pdfPath
