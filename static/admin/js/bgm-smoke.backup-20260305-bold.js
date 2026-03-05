// static/admin/js/bgm-smoke.js
// Backup of the previous live version:
// static/admin/js/bgm-smoke.backup-20260305.js
(function init() {
  if (window.__bgmSmokeInit) return;
  window.__bgmSmokeInit = true;

  // Decorative effect only: don't run when reduced motion or data saver is enabled.
  if (window.__bgmSmokeStarted) return;
  const forceSmoke = window.__bgmSmokeForce === true;

  const prefersReduced =
    window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const saveData = !!(navigator.connection && navigator.connection.saveData);
  if (!forceSmoke && (prefersReduced || saveData)) return;

  let host = document.getElementById('bg');
  if (!host && document.readyState === 'loading') {
    document.addEventListener(
      'DOMContentLoaded',
      () => {
        window.__bgmSmokeInit = false;
        init();
      },
      { once: true }
    );
    return;
  }
  if (!host && document.body) {
    host = document.createElement('div');
    host.id = 'bg';
    host.setAttribute('aria-hidden', 'true');
    document.body.prepend(host);
  }
  if (!host) return;
  host.style.position = 'fixed';
  host.style.inset = '0';
  host.style.pointerEvents = 'none';
  if (!host.style.zIndex) host.style.zIndex = '0';
  host.style.background = [
    'radial-gradient(circle at 50% 18%, rgba(8, 12, 20, 0.28) 0%, rgba(3, 4, 8, 0.68) 48%, rgba(0, 0, 0, 0.92) 100%)',
    'linear-gradient(180deg, rgba(0, 0, 0, 0.18) 0%, rgba(0, 0, 0, 0.54) 55%, rgba(0, 0, 0, 0.78) 100%)',
  ].join(',');
  host.style.backgroundBlendMode = 'normal, multiply';

  const loadThreeScript = (src) =>
    new Promise((resolve, reject) => {
      const existing = Array.from(document.querySelectorAll('script[data-bgm-three="1"]')).find(
        (script) => script.getAttribute('src') === src || script.src === src
      );
      if (existing) {
        if (window.THREE) {
          resolve(window.THREE);
          return;
        }
        existing.addEventListener(
          'load',
          () => (window.THREE ? resolve(window.THREE) : reject(new Error('THREE unavailable'))),
          { once: true }
        );
        existing.addEventListener('error', () => reject(new Error('Failed to load THREE')), {
          once: true,
        });
        return;
      }

      const script = document.createElement('script');
      script.src = src;
      script.async = true;
      script.dataset.bgmThree = '1';
      script.addEventListener(
        'load',
        () => (window.THREE ? resolve(window.THREE) : reject(new Error('THREE unavailable'))),
        { once: true }
      );
      script.addEventListener(
        'error',
        () => {
          script.remove();
          reject(new Error('Failed to load THREE'));
        },
        { once: true }
      );
      document.head.appendChild(script);
    });

  const ensureThreeLoaded = () => {
    if (window.THREE) return Promise.resolve(window.THREE);
    if (window.__bgmSmokeThreePromise) return window.__bgmSmokeThreePromise;

    const sources = [];
    const pushSource = (value) => {
      if (!value || typeof value !== 'string') return;
      if (!sources.includes(value)) sources.push(value);
    };
    pushSource(window.__bgmSmokeThreeSrc);
    pushSource(window.__bgmSmokeThreeFallbackSrc);
    pushSource('https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.min.js');
    pushSource('https://unpkg.com/three@0.160.0/build/three.min.js');

    const trySource = (index) => {
      if (index >= sources.length) {
        return Promise.reject(new Error('No THREE source could be loaded'));
      }
      return loadThreeScript(sources[index]).catch(() => trySource(index + 1));
    };

    window.__bgmSmokeThreePromise = trySource(0).catch((error) => {
      window.__bgmSmokeThreePromise = null;
      throw error;
    });

    return window.__bgmSmokeThreePromise;
  };

  const startCanvasFallback = () => {
    if (window.__bgmSmokeStarted) return;
    window.__bgmSmokeStarted = true;

    const canvas = document.createElement('canvas');
    canvas.setAttribute('aria-hidden', 'true');
    canvas.style.position = 'absolute';
    canvas.style.inset = '0';
    canvas.style.width = '100%';
    canvas.style.height = '100%';
    canvas.style.display = 'block';
    canvas.style.opacity = '0.82';
    canvas.style.mixBlendMode = 'screen';
    host.appendChild(canvas);

    const ctx = canvas.getContext('2d', { alpha: true });
    if (!ctx) return;

    const baseFps = 24;
    const frameMs = 1000 / baseFps;
    let lastFrame = 0;
    let raf = 0;
    let pxW = 1;
    let pxH = 1;
    let dpr = 1;
    let particles = [];

    const spawnParticle = () => ({
      x: Math.random() * pxW,
      y: pxH + Math.random() * (pxH * 0.3),
      r: (Math.random() * 120 + 72) * dpr,
      vx: (Math.random() - 0.5) * 0.38 * dpr,
      vy: -(Math.random() * 0.56 + 0.3) * dpr,
      alpha: Math.random() * 0.07 + 0.04,
      wobbleSeed: Math.random() * Math.PI * 2,
    });

    const resetParticle = (p) => {
      p.x = Math.random() * pxW;
      p.y = pxH + Math.random() * (pxH * 0.25);
      p.r = (Math.random() * 120 + 72) * dpr;
      p.vx = (Math.random() - 0.5) * 0.38 * dpr;
      p.vy = -(Math.random() * 0.56 + 0.3) * dpr;
      p.alpha = Math.random() * 0.07 + 0.04;
      p.wobbleSeed = Math.random() * Math.PI * 2;
    };

    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 1.25);
      pxW = Math.max(1, Math.floor(window.innerWidth * dpr));
      pxH = Math.max(1, Math.floor(window.innerHeight * dpr));
      canvas.width = pxW;
      canvas.height = pxH;
      const targetCount = Math.min(56, Math.max(26, Math.round((pxW * pxH) / 70000)));
      if (particles.length > targetCount) {
        particles.length = targetCount;
      } else {
        while (particles.length < targetCount) particles.push(spawnParticle());
      }
    };

    const drawParticle = (p) => {
      const gradient = ctx.createRadialGradient(
        p.x,
        p.y,
        p.r * 0.2,
        p.x,
        p.y,
        p.r
      );
      gradient.addColorStop(0, `rgba(244,247,255,${p.alpha})`);
      gradient.addColorStop(0.58, `rgba(214,225,252,${p.alpha * 0.66})`);
      gradient.addColorStop(1, 'rgba(145,165,210,0)');
      ctx.fillStyle = gradient;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fill();
    };

    const render = (now) => {
      raf = requestAnimationFrame(render);
      if (document.hidden) return;
      if (now - lastFrame < frameMs) return;
      lastFrame = now;

      ctx.clearRect(0, 0, pxW, pxH);
      for (let i = 0; i < particles.length; i += 1) {
        const p = particles[i];
        const wobble = Math.sin(now * 0.001 + p.wobbleSeed + p.y * 0.0045) * 0.3 * dpr;
        p.x += p.vx + wobble;
        p.y += p.vy;
        if (p.y < -p.r || p.x < -p.r * 1.3 || p.x > pxW + p.r * 1.3) {
          resetParticle(p);
        }
        drawParticle(p);
      }
    };

    const stop = () => {
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
    };

    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        stop();
      } else if (!raf) {
        lastFrame = 0;
        raf = requestAnimationFrame(render);
      }
    });

    let resizeRaf = 0;
    addEventListener('resize', () => {
      if (resizeRaf) cancelAnimationFrame(resizeRaf);
      resizeRaf = requestAnimationFrame(() => {
        resizeRaf = 0;
        resize();
      });
    });

    resize();
    raf = requestAnimationFrame(render);
  };

  const start = () => {
    if (!window.THREE || window.__bgmSmokeStarted) return false;
    window.__bgmSmokeStarted = true;

    // Lower the pixel ratio to reduce GPU work; the effect is purely decorative.
    const clampedDpr = Math.min(window.devicePixelRatio || 1, 1.25);

    let renderer;
    try {
      renderer = new THREE.WebGLRenderer({
        antialias: false,
        powerPreference: 'low-power',
      });
    } catch (error) {
      window.__bgmSmokeStarted = false;
      return false;
    }
    renderer.setPixelRatio(clampedDpr);
    renderer.setSize(window.innerWidth, window.innerHeight);
    if ('outputColorSpace' in renderer) renderer.outputColorSpace = THREE.SRGBColorSpace;
    host.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
    const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), null);
    scene.add(quad);

    const frag = `
      precision highp float;
      uniform vec2  iResolution;
      uniform float iTime;
      uniform float uDensity, uRise, uWind, uTurbulence, uFill, uContrast, uGrain, uQuality;

      float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7)))*43758.5453123); }
      float noise(vec2 p){
        vec2 i=floor(p), f=fract(p);
        float a=hash(i), b=hash(i+vec2(1.,0.));
        float c=hash(i+vec2(0.,1.)), d=hash(i+vec2(1.,1.));
        vec2 u=f*f*(3.-2.*f);
        return mix(a,b,u.x)+(c-a)*u.y*(1.-u.x)+(d-b)*u.x*u.y;
      }
      float fbm(vec2 p){
        float v=0., a=0.5; mat2 m=mat2(1.6,1.2,-1.2,1.6);
        // 4 octaves is plenty for this background, and cuts GPU work noticeably.
        for(int i=0;i<4;i++){ v+=a*noise(p); p=m*p; a*=0.5; }
        return v;
      }
      float bottomEmitter(float y, float fill){
        float edge = mix(0.35, 1.05, fill);
        float k = 1.0 - smoothstep(0.0, edge, y);
        return pow(k, 1.1);
      }
      vec3 tonemap(vec3 x){ x=max(x, vec3(0.0)); return x/(1.0+x); }

      void main(){
        vec2 uv = gl_FragCoord.xy / iResolution.xy;
        vec2 p = uv; p.x *= iResolution.x/iResolution.y;
        float t = iTime, rise = 0.12 * uRise;
        float ripple = sin((uv.y * 16.0) - (t * (1.1 + uTurbulence * 0.22)) + fbm(vec2(uv.x * 4.5, uv.y * 3.2 + t * 0.15)) * 2.4);
        p.x += ripple * (0.02 + uTurbulence * 0.004);

        float d = 0.0;
        vec2 s1 = vec2(p.x + uWind*t*0.03, p.y - t*rise*0.6);  d += fbm(s1*1.2 + vec2(0.0,  t*0.10)) * 0.9;
        vec2 s2 = vec2(p.x*1.5 + uWind*t*0.05, p.y - t*rise*0.9); d += fbm(s2*2.0 + vec2(0.0, -t*0.15)) * 0.7;

        float q = mix(3.0, 5.0, uQuality);
        vec2 s3 = vec2(p.x*2.2 + uWind*t*0.07, p.y - t*rise*1.25); d += fbm(s3*q + vec2(t*0.12, 0.0)) * 0.55;

        d /= 2.15; d = pow(d, 1.35 + uTurbulence*0.08); d *= uDensity;

        float emit = bottomEmitter(uv.y, uFill); d *= mix(0.6, 1.0, emit);
        float topFade = smoothstep(0.88*uFill, 1.04, uv.y); d *= (1.0 - 0.24*topFade);

        float g = (noise(uv * iResolution.xy * (48.0 + uQuality*64.0) + iTime*10.0) - 0.5) * uGrain;

        float smoke = clamp(d * uContrast + g, 0.0, 1.0);
        smoke *= 1.0 + ripple * 0.1;
        float hx = smoothstep(0.0, 0.15, uv.x) * (1.0 - smoothstep(0.85, 1.0, uv.x));
        smoke *= mix(0.95, 1.0, hx);

        vec3 tint = vec3(0.86, 0.9, 1.0);
        vec3 col = vec3(smoke) * tint;
        col = tonemap(col * 2.9);
        gl_FragColor = vec4(col, 1.0);
      }
    `;

    const uniforms = {
      iResolution: { value: new THREE.Vector2(window.innerWidth, window.innerHeight) },
      iTime:       { value: 0 },
      uDensity:    { value: 0.68 },
      uRise:       { value: 0.58 },
      uWind:       { value: 0.22 },
      uTurbulence: { value: 1.24 },
      uFill:       { value: 0.82 },
      uContrast:   { value: 1.22 },
      uGrain:      { value: 0.0 },
      uQuality:    { value: 0.7 },
    };

    quad.material = new THREE.ShaderMaterial({
      uniforms,
      vertexShader: `void main(){gl_Position=vec4(position,1.0);}`,
      fragmentShader: frag,
      transparent: false,
      depthWrite: false,
      depthTest: false,
    });

    const targetFps = 30;
    const frameMs = 1000 / targetFps;
    const startedAt = performance.now();
    let lastFrame = 0;
    let raf = 0;

    const renderFrame = (now) => {
      raf = requestAnimationFrame(renderFrame);
      if (document.hidden) return;
      if (now - lastFrame < frameMs) return;
      lastFrame = now;
      uniforms.iTime.value = (now - startedAt) / 1000;
      renderer.render(scene, camera);
    };

    const stop = () => {
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
    };

    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        stop();
      } else if (!raf) {
        lastFrame = 0;
        raf = requestAnimationFrame(renderFrame);
      }
    });

    raf = requestAnimationFrame(renderFrame);

    let resizeRaf = 0;
    addEventListener('resize', () => {
      if (resizeRaf) cancelAnimationFrame(resizeRaf);
      resizeRaf = requestAnimationFrame(() => {
        resizeRaf = 0;
        uniforms.iResolution.value.set(window.innerWidth, window.innerHeight);
        renderer.setSize(window.innerWidth, window.innerHeight);
      });
    });
    return true;
  };

  const events = [
    'pointerdown',
    'pointermove',
    'touchstart',
    'touchmove',
    'wheel',
    'scroll',
    'keydown',
  ];
  let activated = false;

  const cleanup = () => {
    events.forEach((eventName) => window.removeEventListener(eventName, onFirstInteraction, true));
  };

  const onFirstInteraction = () => {
    if (activated) return;
    activated = true;
    cleanup();

    ensureThreeLoaded()
      .then(() => {
        const started = start();
        if (!started) startCanvasFallback();
      })
      .catch(() => {
        startCanvasFallback();
      });
  };

  events.forEach((eventName) => window.addEventListener(eventName, onFirstInteraction, true));

  const shouldAutoStart = window.__bgmSmokeAutoStart !== false;
  const rawDelay = Number(window.__bgmSmokeAutoDelayMs);
  const autoStartDelayMs = Number.isFinite(rawDelay) ? Math.max(0, rawDelay) : 450;
  if (shouldAutoStart) {
    const scheduleAutoStart = () => window.setTimeout(onFirstInteraction, autoStartDelayMs);
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', scheduleAutoStart, { once: true });
    } else {
      scheduleAutoStart();
    }
  }
})();
