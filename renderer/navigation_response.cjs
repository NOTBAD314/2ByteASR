// Recover one missing CDP navigation response on an owned local bundle page.
// A null response can accompany a completed document load; real HTTP errors
// and thrown navigation errors retain Remotion's normal failure handling.
function isBundleNavigation(options) {
  try {
    const url = new URL(options.url);
    return url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
      && ['/', '/index.html'].includes(url.pathname);
  } catch { return false; }
}
function wrapBundleNavigation(navigate, report = () => {}) {
  return async function(options) {
    const response = await navigate.call(this, options);
    if (response !== null || !isBundleNavigation(options)) return response;
    report({phase:'navigation_response_missing', url:options.url, attempt:1});
    const retried = await navigate.call(this, options);
    report({phase:'navigation_response_retry', url:options.url, recovered:retried !== null, attempt:2});
    return retried;
  };
}
module.exports = {isBundleNavigation, wrapBundleNavigation};
