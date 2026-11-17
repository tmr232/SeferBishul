if ("wakeLock" in navigator) {
  let wakeLock = null;
  let requesting = false;

  const requestWakeLock = async () => {
    if (
      wakeLock !== null ||
      requesting ||
      document.visibilityState !== "visible"
    ) {
      return;
    }

    requesting = true;
    try {
      wakeLock = await navigator.wakeLock.request("screen");
      wakeLock.addEventListener("release", () => {
        wakeLock = null;
      });
    } catch (err) {
      console.log("Could not acquire screen wake lock:", err);
    } finally {
      requesting = false;
    }
  };

  // Some mobile browsers require a user gesture before granting a wake lock.
  // The first normal interaction enables it by default, without a special control.
  for (const eventName of ["pointerdown", "touchstart", "keydown"]) {
    document.addEventListener(eventName, requestWakeLock, { passive: true });
  }

  // A wake lock is released when the page becomes hidden.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      requestWakeLock();
    }
  });
}
