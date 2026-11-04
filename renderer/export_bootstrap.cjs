// Extend the existing process policy with a bounded local-navigation guard.
const path = require('node:path');
const rendererDist = path.dirname(require.resolve('@remotion/renderer'));
const {Page} = require(path.join(rendererDist, 'browser', 'BrowserPage.js'));
const {wrapBundleNavigation} = require('./navigation_response.cjs');
const marker = Symbol.for('2byte.navigation-response-guard');
if (!Page.prototype[marker]) {
  Page.prototype.goto = wrapBundleNavigation(Page.prototype.goto, value => {
    if (process.env.TWOBYTEASR_CHILD_PROCESS_LOG) {
      require('node:fs').appendFileSync(process.env.TWOBYTEASR_CHILD_PROCESS_LOG,
        JSON.stringify({timestamp:new Date().toISOString(),parent_pid:process.pid,
          job_id:process.env.TWOBYTEASR_EXPORT_JOB_ID,...value})+'\n');
    }
  });
  Page.prototype[marker] = true;
}
