// TotoSit.jsx
// 또또 — 사주 보는 검은 고양이 (단일 포즈)
// 슬림한 검은 실루엣 + 큰 흰 눈
// ─────────────────────────────────────────────────────────────────
//
// 사용법:
//   <link rel="stylesheet" href="toto-animations.css" />
//   <TotoSit size={280} animated />
//
// Props:
//   size     — number, 너비(px). 비율 자동 유지. 기본 280
//   animated — boolean, 애니메이션 on/off. 기본 true
// ─────────────────────────────────────────────────────────────────

const TOTO = {
  fur:   '#0a0610',  // 털 (검정)
  eye:   '#ffffff',  // 흰 눈
  pupil: '#0a0610',  // 동공
};

// 흰 눈 — oval + 세로 검정 동공 + 점광
function Eye({ cx, cy, rx = 15, ry = 20, pupilRx = 3.2, pupilRy = 8, look = [0, 0], shine = true }) {
  return (
    <g>
      <ellipse cx={cx} cy={cy} rx={rx} ry={ry} fill={TOTO.eye} />
      <ellipse
        cx={cx + look[0]}
        cy={cy + look[1]}
        rx={pupilRx}
        ry={pupilRy}
        fill={TOTO.pupil}
      />
      {shine && (
        <circle
          cx={cx + look[0] - pupilRx * 0.5}
          cy={cy + look[1] - pupilRy * 0.6}
          r={1.4}
          fill="#ffffff"
        />
      )}
    </g>
  );
}

function TotoSit({ size = 280, animated = true }) {
  return (
    <svg
      viewBox="0 0 220 360"
      width={size}
      height={size * (360 / 220)}
      className={animated ? 'toto toto-anim' : 'toto'}
    >
      {/* 바닥 그림자 */}
      <ellipse cx="110" cy="346" rx="66" ry="6" fill={TOTO.fur} opacity="0.18" />

      {/* 꼬리 — 몸 뒤에서 자연스럽게 빠져나옴 */}
      <g className="toto-tail" style={{ transformOrigin: '160px 320px' }}>
        <path
          d="M 90 318
             Q 160 352 202 335
             Q 224 308 220 254
             Q 214 226 192 232
             Q 184 244 192 258
             Q 205 280 188 306
             Q 145 326 110 322 Z"
          fill={TOTO.fur}
        />
      </g>

      {/* 몸통 — 슬림 teardrop */}
      <g className="toto-body" style={{ transformOrigin: '110px 320px' }}>
        <path
          d="M 90 165
             Q 70 220 62 280
             Q 60 332 90 340
             Q 110 346 130 340
             Q 160 332 158 280
             Q 150 220 130 165 Z"
          fill={TOTO.fur}
        />
      </g>

      {/* 머리 — 둥글고 넓은 + 긴 귀 */}
      <g className="toto-head">
        <path
          d="M 50 80
             Q 26 88 22 115
             Q 26 158 80 162
             Q 110 165 140 162
             Q 194 158 198 115
             Q 194 88 170 80
             L 150 12
             L 132 78
             Q 110 70 88 78
             L 70 12
             L 50 80 Z"
          fill={TOTO.fur}
        />
      </g>

      {/* 눈 — 큰 흰 oval + 세로 검정 동공 */}
      <g className="toto-eyes">
        <g className="toto-eye toto-eye-left" style={{ transformOrigin: '85px 115px' }}>
          <Eye cx={85} cy={115} />
        </g>
        <g className="toto-eye toto-eye-right" style={{ transformOrigin: '135px 115px' }}>
          <Eye cx={135} cy={115} />
        </g>
      </g>
    </svg>
  );
}

// React 빌드 환경이라면 export
// export default TotoSit;

// 빌드 없이 <script type="text/babel">로 쓸 때는 window에 노출
if (typeof window !== 'undefined') {
  Object.assign(window, { TotoSit, TOTO, Eye });
}
