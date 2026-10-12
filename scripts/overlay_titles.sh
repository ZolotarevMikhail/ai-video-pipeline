#!/bin/zsh
# Наложение титров на ролик «Море зовёт!» (20 сек, 480x854, 9:16).
# Титры вверху (~12% от высоты) — чтобы плашка плеера не перекрывала их:
# полупрозрачные белые, шрифт Arial Rounded Bold в стилистике клипа.
#
# Запуск:  zsh overlay_titles.sh [входной.mp4] [выходной.mp4]
# По умолчанию: вход — rolik-moze-zovet-20s-480p.mp4, выход — rolik-titry.mp4

IN="${1:-rolik-moze-zovet-20s-480p.mp4}"
OUT="${2:-rolik-titry.mp4}"
FONT="/System/Library/Fonts/Supplemental/Comic Sans MS Bold.ttf"

# Выбираем ffmpeg, в сборке которого есть drawtext:
# формулы Homebrew 9+ собираются без него, поэтому при необходимости
# переключаемся на классическую ffmpeg@7.
FFMPEG="$(command -v ffmpeg)"
if ! "$FFMPEG" -hide_banner -filters 2>/dev/null | grep -q drawtext \
   && [ -x /opt/homebrew/opt/ffmpeg@7/bin/ffmpeg ]; then
  FFMPEG="/opt/homebrew/opt/ffmpeg@7/bin/ffmpeg"
fi

# Полупрозрачность (0..1): базовый итог 0.6, с плавным появлением за 0.4 сек
ALPHA_IN_4="0.6*min(min(t/0.4,1),min((4-t)/0.4,1))"
ALPHA_16_20="0.6*min(min((t-16)/0.4,1),min((20-t)/0.4,1))"

"$FFMPEG" -y -i "$IN" \
  -vf "drawtext=fontfile='${FONT}':text='МОРЕ ЗОВЁТ!':fontsize=42:fontcolor=white:x=(w-text_w)/2:y=h*0.12:alpha='${ALPHA_IN_4}':shadowcolor=black@0.4:shadowx=2:shadowy=2:enable='between(t,0,4)',
       drawtext=fontfile='${FONT}':text='УРА! МОРЕ!':fontsize=42:fontcolor=white:x=(w-text_w)/2:y=h*0.12:alpha='${ALPHA_16_20}':shadowcolor=black@0.4:shadowx=2:shadowy=2:enable='between(t,16,20)'" \
  -c:v libx264 -crf 21 -profile:v main -level 3.1 -r 25 -pix_fmt yuv420p \
  -movflags +faststart \
  -c:a aac -b:a 128k \
  "$OUT"

echo "Готово: $OUT (звуковая дорожка скопирована без перекодирования)"