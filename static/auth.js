/**
 * auth.js — SatyaX ClerkJS Frontend Integration
 * Initialises Clerk, manages auth-aware navbar, and provides token helpers.
 */

/* ── ClerkJS Ready Helper ── */
async function waitForClerk(timeout = 5000) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const check = () => {
      if (window.Clerk && window.Clerk.loaded) return resolve(window.Clerk);
      if (window.Clerk) {
        window.Clerk.load()
          .then(() => resolve(window.Clerk))
          .catch(reject);
        return;
      }
      if (Date.now() - start > timeout) return reject(new Error('Clerk load timeout'));
      setTimeout(check, 80);
    };
    check();
  });
}

/* ── Auth-Aware Navbar ── */
async function initAuthNav() {
  try {
    const clerk = await waitForClerk();
    const user = clerk.user;

    // Elements that appear in all templates
    const navSignedOut = document.getElementById('nav-signed-out');
    const navSignedIn  = document.getElementById('nav-signed-in');
    const navAvatar    = document.getElementById('nav-avatar');
    const navUserName  = document.getElementById('nav-username');
    const navAdminLink = document.getElementById('nav-admin-link');

    if (user) {
      // Logged-in state
      if (navSignedOut) navSignedOut.style.display = 'none';
      if (navSignedIn)  navSignedIn.style.display  = 'flex';
      if (navAvatar) {
        navAvatar.src = user.imageUrl || '/static/logo.jpg';
        navAvatar.alt = user.fullName || user.primaryEmailAddress?.emailAddress || 'User';
      }
      if (navUserName) {
        navUserName.textContent = user.firstName || user.primaryEmailAddress?.emailAddress?.split('@')[0] || 'User';
      }
      // Show admin link if role is admin
      const role = user.publicMetadata?.role;
      if (navAdminLink && role === 'admin') {
        navAdminLink.style.display = 'inline-flex';
      }
    } else {
      // Logged-out state
      if (navSignedOut) navSignedOut.style.display = 'flex';
      if (navSignedIn)  navSignedIn.style.display  = 'none';
    }
  } catch (err) {
    // Clerk not configured yet — show signed-out state
    const navSignedOut = document.getElementById('nav-signed-out');
    const navSignedIn  = document.getElementById('nav-signed-in');
    if (navSignedOut) navSignedOut.style.display = 'flex';
    if (navSignedIn)  navSignedIn.style.display  = 'none';
  }
}

/* ── Sign Out ── */
async function satyaxSignOut() {
  try {
    const clerk = await waitForClerk();
    await clerk.signOut();
    window.location.href = '/';
  } catch (err) {
    window.location.href = '/';
  }
}

/* ── Get Auth Token (for API calls) ── */
async function getAuthToken() {
  try {
    const clerk = await waitForClerk();
    if (!clerk.user) return null;
    return await clerk.session?.getToken();
  } catch {
    return null;
  }
}
window.getAuthToken = getAuthToken;

/* ── Mount Clerk SignIn Component ── */
async function mountSignIn(elementId, opts = {}) {
  try {
    const clerk = await waitForClerk();
    clerk.mountSignIn(document.getElementById(elementId), {
      routing: 'virtual',
      afterSignInUrl: '/dashboard',
      signUpUrl: '/sign-up',
      appearance: {
        layout: {
          socialButtonsLayout: 'blockButton',
          socialButtonsPlacement: 'top'
        }
      },
      ...opts,
    });
  } catch (err) {
    console.warn('[SatyaX auth] SignIn mount failed:', err);
  }
}

/* ── Mount Clerk SignUp Component ── */
async function mountSignUp(elementId, opts = {}) {
  try {
    const clerk = await waitForClerk();
    clerk.mountSignUp(document.getElementById(elementId), {
      routing: 'virtual',
      afterSignUpUrl: '/dashboard',
      signInUrl: '/sign-in',
      appearance: {
        layout: {
          socialButtonsLayout: 'blockButton',
          socialButtonsPlacement: 'top'
        }
      },
      ...opts,
    });
  } catch (err) {
    console.warn('[SatyaX auth] SignUp mount failed:', err);
  }
}

/* ── Mount User Profile ── */
async function mountUserProfile(elementId, opts = {}) {
  try {
    const clerk = await waitForClerk();
    clerk.mountUserProfile(document.getElementById(elementId), opts);
  } catch (err) {
    console.warn('[SatyaX auth] UserProfile mount failed:', err);
  }
}

/* ── Auto-init on every page ── */
document.addEventListener('DOMContentLoaded', () => {
  initAuthNav();
});
