// PPE Monitor 대시보드 (E 담당)
// server가 "/"에서 이 파일을 서빙하므로 API는 /api/... 상대 경로로 호출합니다.

// 시연 영상 목록. 첫 번째 영상이 기본으로 재생됩니다.
// start: 재생을 시작할 초 (앞부분에 쓸 수 없는 장면이 있을 때)
const VIDEOS = [
  { label: "정상 (현장 투어)", id: "DLknkTG1EpE" },
  { label: "정상 + 조끼 미착용", id: "w0n0TnwQPXc" },
  { label: "안전모 미착용", id: "PHezq3zCgGs", start: 31 },
];

const LATEST_POLL_MS = 500;  // 실시간 화면이 끊겨 보이지 않도록 0.5초마다 확인 (frame_ts가 바뀔 때만 이미지 교체)
const EVENTS_POLL_MS = 5000;

const $ = (id) => document.getElementById(id);

// ---------------- YouTube 플레이어 ----------------

let player = null;
let currentStart = 0;

function onYouTubeIframeAPIReady() {
  const first = VIDEOS[0].id;
  player = new YT.Player("player", {
    videoId: first,
    playerVars: {
      autoplay: 1,
      mute: 1,          // 자동재생 정책 때문에 음소거로 시작
      loop: 1,
      playlist: first,  // loop가 동작하려면 playlist에 같은 ID가 필요
      playsinline: 1,
      rel: 0,
    },
    events: {
      onError: onPlayerError,
      onStateChange: onPlayerStateChange,
    },
  });
  setActiveButton(first);
}
window.onYouTubeIframeAPIReady = onYouTubeIframeAPIReady;

function onPlayerError(e) {
  if (e.data === 101 || e.data === 150) {
    $("video-msg").textContent = "퍼가기 금지 영상입니다. 다른 영상을 골라 주세요.";
  } else {
    $("video-msg").textContent = "영상을 재생할 수 없습니다 (오류 " + e.data + ").";
  }
}

// loadVideoById로 바꾼 영상은 playlist 설정이 없어서, 끝나면 직접 처음으로 돌립니다.
function onPlayerStateChange(e) {
  if (e.data === YT.PlayerState.ENDED) {
    player.seekTo(currentStart);
    player.playVideo();
  }
}

function playVideo(id, start = 0) {
  $("video-msg").textContent = "";
  currentStart = start;
  setActiveButton(id);
  if (player && player.loadVideoById) player.loadVideoById({ videoId: id, startSeconds: start });
}

function setActiveButton(id) {
  document.querySelectorAll("#video-buttons button").forEach((b) => {
    b.classList.toggle("active", b.dataset.id === id);
  });
}

// watch?v=ID, youtu.be/ID, shorts/ID, embed/ID, 또는 ID만 입력한 경우를 처리
function parseVideoId(text) {
  text = text.trim();
  if (/^[\w-]{11}$/.test(text)) return text;
  const m = text.match(/(?:[?&]v=|youtu\.be\/|\/shorts\/|\/embed\/)([\w-]{11})/);
  return m ? m[1] : null;
}

function setupVideoControls() {
  const box = $("video-buttons");
  VIDEOS.forEach((v) => {
    const b = document.createElement("button");
    b.textContent = v.label;
    b.dataset.id = v.id;
    b.onclick = () => playVideo(v.id, v.start || 0);
    box.appendChild(b);
  });

  const load = () => {
    const id = parseVideoId($("video-url").value);
    if (!id) {
      $("video-msg").textContent = "YouTube 주소를 인식하지 못했습니다.";
      return;
    }
    playVideo(id);
  };
  $("video-load").onclick = load;
  $("video-url").addEventListener("keydown", (e) => {
    if (e.key === "Enter") load();
  });
}

// ---------------- 상태 표시 ----------------

let lastFrameTs = null;

function setOnline(online) {
  const b = $("badge");
  b.textContent = online ? "online" : "offline";
  b.className = "badge " + (online ? "online" : "offline");
}

function formatTime(ts) {
  if (!ts) return "";
  const d = new Date(ts);
  if (isNaN(d)) return ts;
  return d.toLocaleString("ko-KR", { hour12: false });
}

// /api/latest 응답(interface 6.1)으로 화면을 갱신합니다.
// server 없이 테스트할 때는 브라우저 콘솔에서 render({...}) 로 호출합니다.
function render(latest) {
  setOnline(!!latest.online);

  $("person-count").textContent = latest.person_count ?? 0;
  $("no-helmet").textContent = latest.no_helmet ?? 0;
  $("no-vest").textContent = latest.no_vest ?? 0;
  $("stat-helmet").classList.toggle("bad", latest.no_helmet > 0);
  $("stat-vest").classList.toggle("bad", latest.no_vest > 0);

  // frame_ts가 바뀔 때만 이미지를 다시 요청합니다.
  if (latest.frame_ts && latest.frame_ts !== lastFrameTs) {
    lastFrameTs = latest.frame_ts;
    $("frame").src = "/api/frame?t=" + encodeURIComponent(latest.frame_ts);
    $("frame").style.display = "block";
    $("frame-empty").style.display = "none";
    $("frame-ts").textContent = "마지막 수신: " + formatTime(latest.frame_ts);
  }
}
window.render = render;

// /api/events 응답(interface 6.2)의 items로 위반 목록을 그립니다.
function renderEvents(items) {
  const list = $("events");
  list.innerHTML = "";
  if (!items.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "위반 기록이 없습니다";
    list.appendChild(li);
    return;
  }
  items.forEach((ev) => {
    const li = document.createElement("li");

    if (ev.image_url) {
      const a = document.createElement("a");
      a.href = ev.image_url;
      a.target = "_blank";
      const img = document.createElement("img");
      img.src = ev.image_url;
      img.alt = "위반 사진";
      img.loading = "lazy";
      a.appendChild(img);
      li.appendChild(a);
    }

    const text = document.createElement("div");
    const time = document.createElement("div");
    time.className = "time";
    time.textContent = formatTime(ev.ts);
    const detail = document.createElement("div");
    detail.className = "detail";
    detail.textContent =
      "안전모 미착용 " + ev.no_helmet + " · 조끼 미착용 " + ev.no_vest + " (인원 " + ev.person_count + ")";
    text.appendChild(time);
    text.appendChild(detail);
    li.appendChild(text);

    list.appendChild(li);
  });
}
window.renderEvents = renderEvents;

// ---------------- 폴링 ----------------

async function pollLatest() {
  try {
    const res = await fetch("/api/latest", { cache: "no-store" });
    if (!res.ok) throw new Error(res.status);
    render(await res.json());
  } catch (e) {
    setOnline(false);
  }
}

async function pollEvents() {
  try {
    const res = await fetch("/api/events?only_violations=true&limit=20", { cache: "no-store" });
    if (!res.ok) throw new Error(res.status);
    const data = await res.json();
    renderEvents(data.items || []);
  } catch (e) {
    // 다음 주기에 다시 시도합니다. offline 표시는 pollLatest가 담당합니다.
  }
}

setupVideoControls();
pollLatest();
pollEvents();
setInterval(pollLatest, LATEST_POLL_MS);
setInterval(pollEvents, EVENTS_POLL_MS);
