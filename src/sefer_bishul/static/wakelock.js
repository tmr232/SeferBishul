// test support
let isSupported = false;

if ('wakeLock' in navigator) {
  isSupported = true;
  window.alert("Supported!");
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
      window.alert("Acquired Lock!");
    } catch (err) {
      // if wake lock request fails - usually system related, such as battery
      console.log(err);
      window.alert(err);
    }
  } // requestWakeLock()

  window.alert("Going to request a lock!");
  requestWakeLock();

  const handleVisibilityChange = () => {
    window.alert("Gotta love handling things!");
    if (document.visibilityState === 'visible') {
      requestWakeLock();
    }
  }

  // Losing visibility releases the lock, so we make sure to request it again.
  document.addEventListener('visibilitychange', handleVisibilityChange);
} // isSupported