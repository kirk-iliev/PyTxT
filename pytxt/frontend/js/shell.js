/* PyTxT — application shell (Phase 5 / U0).
 *
 * Renders the shared sticky header: brand + the canonical 6-tab navigation
 * (the Phase-5 information architecture) + the connection-status indicator.
 *
 * This is a *markup-only* component: it injects the header at the top of
 * <body> synchronously on script load, so the `#connectionStatus` /
 * `#connectionStatusLabel` elements exist before the per-page scripts
 * (connection.js, app.js, trajectory.js, threading.js …) look them up and
 * wire `connection.onStatusChange`. For that reason shell.js MUST be the
 * first <script> on every page, and it deliberately does NOT touch
 * `window.connection` itself (which isn't defined yet at this point).
 *
 * Tabs whose pages don't exist yet (built in later Phase-5 milestones) are
 * rendered as disabled placeholders so the full IA is visible now.
 */
(function () {
  'use strict';

  // The canonical Phase-5 IA. `ready:false` tabs are shown disabled until
  // their milestone lands (U1 dashboard/diagnostics, U3 correctors, U4 injection).
  const TABS = [
    { label: 'Dashboard',   href: '/',                ready: true,  match: ['/', '/index.html'] },
    { label: 'Trajectory',  href: '/trajectory.html', ready: true },
    { label: 'Correctors',  href: '/correctors.html', ready: false },
    { label: 'Injection',   href: '/injection.html',  ready: false },
    { label: 'Threading',   href: '/threading.html',  ready: true },
    { label: 'Diagnostics', href: '/diagnostics.html', ready: false },
  ];

  const SOON_TITLE = 'Coming in a later Phase-5 milestone';

  function currentPath() {
    return window.location.pathname || '/';
  }

  function isActive(tab) {
    const here = currentPath();
    const matches = tab.match || [tab.href];
    return matches.includes(here);
  }

  function navHtml() {
    return TABS.map((tab) => {
      if (!tab.ready) {
        return `<span class="nav-tab is-disabled" title="${SOON_TITLE}" aria-disabled="true">${tab.label}<span class="nav-soon">soon</span></span>`;
      }
      const active = isActive(tab) ? ' is-active' : '';
      const aria = isActive(tab) ? ' aria-current="page"' : '';
      return `<a class="nav-tab${active}" href="${tab.href}"${aria}>${tab.label}</a>`;
    }).join('');
  }

  function headerHtml() {
    return `
      <header class="app-header">
        <a class="app-brand" href="/">
          <span class="app-brand__mark">▚</span>
          <span class="app-brand__name">PyTxT</span>
        </a>
        <nav class="app-nav" aria-label="Primary">${navHtml()}</nav>
        <div class="connection-status" id="connectionStatus" data-state="connecting">
          <span class="dot"></span>
          <span class="label" id="connectionStatusLabel">connecting…</span>
        </div>
      </header>`;
  }

  // Inject synchronously so subsequent page scripts find the header elements.
  document.body.insertAdjacentHTML('afterbegin', headerHtml());
})();
