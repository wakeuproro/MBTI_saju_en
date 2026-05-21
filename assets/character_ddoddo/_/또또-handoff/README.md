# 또또 — 사주 보는 검은 고양이 캐릭터

슬림한 검은 실루엣 + 큰 흰 눈. SVG 코드로 그려져서 확대해도 안 깨지고, CSS로 애니메이션 작동.

## 📁 파일

```
또또/
├── TotoSit.jsx          # 또또 컴포넌트 (단일 포즈)
├── toto-animations.css  # 애니메이션 keyframes
└── README.md            # 이 파일
```

## 🐾 사용법

### React 프로젝트에 옮길 때

```jsx
import './toto-animations.css';
import TotoSit from './TotoSit.jsx';

// 어디든
<TotoSit size={280} animated />
```

### Vanilla HTML/JS 프로젝트에 옮길 때

```html
<link rel="stylesheet" href="toto-animations.css" />

<script src="https://unpkg.com/react@18.3.1/umd/react.development.js"></script>
<script src="https://unpkg.com/react-dom@18.3.1/umd/react-dom.development.js"></script>
<script src="https://unpkg.com/@babel/standalone@7.29.0/babel.min.js"></script>
<script type="text/babel" src="TotoSit.jsx"></script>

<div id="toto-mount"></div>
<script type="text/babel">
  ReactDOM.createRoot(document.getElementById('toto-mount'))
    .render(<TotoSit size={280} animated />);
</script>
```

### Props

| 이름       | 타입    | 기본값 | 설명                          |
|------------|---------|--------|-------------------------------|
| `size`     | number  | 280    | 너비(px). 비율 자동 유지      |
| `animated` | boolean | true   | false면 정적 SVG로 작동       |

## 🎬 애니메이션

`.toto-anim` 클래스가 컴포넌트 루트에 있을 때만 작동:

- 눈 깜빡임 (5초마다)
- 꼬리 살랑 (3초 주기)
- 숨쉬기 (3.4초 주기)

일부만 끄고 싶으면 해당 클래스(`.toto-tail`, `.toto-eye-left/right`, `.toto-body`)만 override.

## 🎨 컬러 토큰

`TotoSit.jsx` 안의 `TOTO` 객체에서 바꾸면 색감 변경 가능:

| 토큰       | 기본값      | 용도              |
|------------|-------------|-------------------|
| `fur`      | `#0a0610`   | 털 (검정)         |
| `eye`      | `#ffffff`   | 흰 눈             |
| `pupil`    | `#0a0610`   | 동공              |

예: `fur: '#3a2814'` → 갈색 또또 / `eye: '#ffd84d'` → 노란 눈 또또

## 🛠 권장 배경

- 일반 화면 — 크림 `#fbf4e4`
- 신비로운 분위기 — 딥 퍼플 `#241a3d`

또또는 실루엣이라 어두운 배경에서도 또렷하게 보임 (흰 눈이 포커스 잡음).
