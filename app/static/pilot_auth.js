(() => {
  const nativeFetch = window.fetch.bind(window);
  let promptInFlight = null;

  function apiPath(input) {
    try {
      const value = input instanceof Request ? input.url : String(input);
      const url = new URL(value, window.location.href);
      return url.origin === window.location.origin && url.pathname.startsWith('/api/')
        ? url.pathname
        : '';
    } catch (_error) {
      return '';
    }
  }

  function withToken(input, init, token) {
    const headers = new Headers(
      init?.headers || (input instanceof Request ? input.headers : undefined),
    );
    if (token && !headers.has('Authorization')) {
      headers.set('Authorization', `Bearer ${token}`);
    }
    return { ...(init || {}), headers };
  }

  async function requestToken() {
    if (!promptInFlight) {
      promptInFlight = Promise.resolve().then(() => {
        const token = window.prompt('Enter the BeezaOffice operator token') || '';
        if (token) localStorage.setItem('beezaToken', token);
        return token;
      }).finally(() => {
        promptInFlight = null;
      });
    }
    return promptInFlight;
  }

  window.fetch = async (input, init = {}) => {
    const path = apiPath(input);
    if (!path || path === '/api/health') {
      return nativeFetch(input, init);
    }

    let token = localStorage.getItem('beezaToken') || '';
    let response = await nativeFetch(input, withToken(input, init, token));
    if (response.status !== 401) return response;

    localStorage.removeItem('beezaToken');
    token = await requestToken();
    if (!token) return response;
    response = await nativeFetch(input, withToken(input, init, token));
    if (response.status === 401) localStorage.removeItem('beezaToken');
    return response;
  };
})();
