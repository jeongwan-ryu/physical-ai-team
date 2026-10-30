// D 담당: new EventSource("/events") → present: play / absent·offline: pause
// bridge 없이 테스트: 브라우저 콘솔에서 setState("present" | "absent" | "offline")

const STATES = ["present", "absent", "offline"];

const badge = document.getElementById("badge");
const banner = document.getElementById("banner");
const notice = document.getElementById("notice");
const form = document.getElementById("url-form");
const urlInput = document.getElementById("url");

let state = "offline";
let player = null;
let playerReady = false;
let apiReady = false;
let pendingVideoId = null;

// URL → videoId (watch?v=, youtu.be/, shorts/)
function parseVideoId(input) {
  let url;
  try {
    url = new URL(input.trim());
  } catch {
    return null;
  }
  const host = url.hostname.replace(/^(www\.|m\.)/, "");
  let id = null;
  if (host === "youtu.be") {
    id = url.pathname.split("/")[1];
  } else if (host === "youtube.com" || host === "music.youtube.com") {
    if (url.pathname === "/watch") id = url.searchParams.get("v");
    else if (url.pathname.startsWith("/shorts/")) id = url.pathname.split("/")[2];
  }
  return id && /^[\w-]{11}$/.test(id) ? id : null;
}

function showNotice(text) {
  notice.textContent = text;
  notice.hidden = !text;
}

// 상태를 플레이어에 반영. ready 전이면 state만 저장해 두고 onReady에서 적용
function applyState() {
  if (!playerReady) return;
  if (state === "present") player.playVideo();
  else player.pauseVideo();
}

function setState(next) {
  if (!STATES.includes(next)) {
    console.warn("unknown state:", next);
    return;
  }
  state = next;
  badge.textContent = next;
  badge.className = next;
  banner.hidden = next !== "offline";
  applyState();
}
window.setState = setState;

// SSE: 페이지 로드 시 연결. 재연결은 EventSource가 자동으로 함
const events = new EventSource("/events");
events.onmessage = (e) => {
  try {
    setState(JSON.parse(e.data).state);
  } catch {
    console.warn("bad event:", e.data);
  }
};
events.onerror = () => setState("offline");

// YouTube IFrame API
function createPlayer(videoId) {
  player = new YT.Player("player", {
    videoId,
    playerVars: { playsinline: 1, rel: 0 },
    events: {
      onReady: () => {
        playerReady = true;
        if (pendingVideoId !== videoId) player.cueVideoById(pendingVideoId);
        applyState();
      },
      onError: (e) => {
        if (e.data === 101 || e.data === 150) {
          showNotice("이 영상은 퍼가기가 허용되지 않아 재생할 수 없습니다. 다른 영상을 사용하세요.");
        } else {
          showNotice(`영상을 재생할 수 없습니다 (오류 ${e.data}).`);
        }
      },
    },
  });
}

window.onYouTubeIframeAPIReady = () => {
  apiReady = true;
  if (pendingVideoId) createPlayer(pendingVideoId);
};

// "시작" 클릭 시 플레이어 생성 (브라우저 자동재생 정책)
form.addEventListener("submit", (e) => {
  e.preventDefault();
  const videoId = parseVideoId(urlInput.value);
  if (!videoId) {
    showNotice("YouTube URL을 확인하세요 (watch?v=, youtu.be/, shorts/ 형식).");
    return;
  }
  showNotice("");
  pendingVideoId = videoId;
  if (player) {
    // 이미 있는 플레이어는 영상만 교체 (ready 전이면 onReady에서 교체)
    if (playerReady) {
      player.cueVideoById(videoId);
      applyState();
    }
  } else if (apiReady) {
    createPlayer(videoId);
  }
});
