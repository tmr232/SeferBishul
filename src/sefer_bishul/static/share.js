(() => {
  const link = document.getElementById("share-link");
  const status = document.getElementById("share-status");
  const data = { title: document.title, url: link.href };
  let shareAttempt = 0;
  let statusTimeout;

  function showStatus(message, attempt) {
    if (attempt !== shareAttempt) return;
    clearTimeout(statusTimeout);
    status.textContent = message;
    if (message) {
      statusTimeout = setTimeout(() => {
        status.textContent = "";
      }, 5000);
    }
  }

  async function copyLink(attempt) {
    try {
      await navigator.clipboard.writeText(link.href);
      showStatus("הקישור הועתק.", attempt);
    } catch {
      showStatus(
        "להעתקת הקישור, לחצו לחיצה ארוכה על ״שיתוף״ או השתמשו בלחצן הימני בעכבר.",
        attempt,
      );
    }
  }

  link.addEventListener("click", async (event) => {
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    )
      return;
    event.preventDefault();
    const attempt = ++shareAttempt;
    showStatus("", attempt);
    try {
      if (
        navigator.share &&
        (!navigator.canShare || navigator.canShare(data))
      ) {
        await navigator.share(data);
      } else {
        await copyLink(attempt);
      }
    } catch (error) {
      if (attempt !== shareAttempt) return;
      if (error.name === "AbortError") {
        showStatus("השיתוף בוטל או שאין יעד זמין.", attempt);
      } else {
        await copyLink(attempt);
      }
    }
  });
})();
