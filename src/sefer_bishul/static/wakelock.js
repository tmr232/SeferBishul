// test support
let isSupported = false;

if ('wakeLock' in navigator) {
  isSupported = true;
} else {
  window.alert("Unsupported!");
}

if (isSupported) {
  // create a reference for the wake lock
  let wakeLock = null;

  // create an async function to request a wake lock
  const requestWakeLock = async () => {
    try {
      wakeLock = await navigator.wakeLock.request('screen');
    } catch (err) {
      // if wake lock request fails - usually system related, such as battery
      console.log(err);
    }
  } // requestWakeLock()

  requestWakeLock();

  const handleVisibilityChange = () => {
    if (document.visibilityState === 'visible') {
      requestWakeLock();
    }
  }

  // Losing visibility releases the lock, so we make sure to request it again.
  document.addEventListener('visibilitychange', handleVisibilityChange);
} // isSupported