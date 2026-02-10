// static/admin/js/bgm-smoke.js
(function init() {
  // Don't run the decorative smoke effect if the user asked for reduced motion,
  // if data-saver is enabled, or if we've already started once.
  if (window.__bgmSmokeStarted) return;
  const prefersReduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const saveData = !!(navigator.connection && navigator.connection.saveData);
  if (prefersReduced || saveData) return;

  const schedule = (startFn) => {
    let started = false;
    const startOnce = () => {
      if (started) return;
      started = true;
      startFn();
    };

    // First user interaction: start immediately (keeps Lighthouse / initial load lighter).
    const onFirstInteraction = () => {
      cleanup();
      startOnce();
    };

    const events = ['pointerdown', 'touchstart', 'scroll', 'wheel', 'keydown', 'mousemove'];
    const opts = { passive: true, capture: true };
    events.forEach((ev) => window.addEventListener(ev, onFirstInteraction, opts));

    const cleanup = () => {
      events.forEach((ev) => window.removeEventListener(ev, onFirstInteraction, opts));
    };

    const idleStart = () => {
      if (started) return;
      cleanup();
      startOnce();
    };

    const runIdle = () => {
      if ('requestIdleCallback' in window) {
        // Delay long-running animation until well after initial paint/TTI.
        window.requestIdleCallback(idleStart, { timeout: 10000 });
      } else {
        window.setTimeout(idleStart, 8000);
      }
    };

    if (document.readyState === 'complete') {
      runIdle();
    } else {
      window.addEventListener('load', runIdle, { once: true });
    }
  };

  const start = () => {
    // дождаться DOM, если #bg ещё не в дереве
    const host = document.getElementById('bg');
    if (!host) return;
    if (!window.THREE) {
      console.warn('THREE not loaded');
      return;
    }
    if (window.__bgmSmokeStarted) return;
    window.__bgmSmokeStarted = true;

    // Lower the pixel ratio to reduce GPU work; the effect is purely decorative.
    const clampedDpr = Math.min(window.devicePixelRatio || 1, 1.25);

    const renderer = new THREE.WebGLRenderer({
      antialias: false,
      powerPreference: 'low-power',
    });
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

        float d = 0.0;
        vec2 s1 = vec2(p.x + uWind*t*0.03, p.y - t*rise*0.6);  d += fbm(s1*1.2 + vec2(0.0,  t*0.10)) * 0.9;
        vec2 s2 = vec2(p.x*1.5 + uWind*t*0.05, p.y - t*rise*0.9); d += fbm(s2*2.0 + vec2(0.0, -t*0.15)) * 0.7;

        float q = mix(3.0, 5.0, uQuality);
        vec2 s3 = vec2(p.x*2.2 + uWind*t*0.07, p.y - t*rise*1.25); d += fbm(s3*q + vec2(t*0.12, 0.0)) * 0.55;

        d /= 2.15; d = pow(d, 1.35 + uTurbulence*0.08); d *= uDensity;

        float emit = bottomEmitter(uv.y, uFill); d *= mix(0.6, 1.0, emit);
        float topFade = smoothstep(0.85*uFill, 1.05, uv.y); d *= (1.0 - 0.35*topFade);

        float g = (noise(uv * iResolution.xy * (48.0 + uQuality*64.0) + iTime*10.0) - 0.5) * uGrain;

        float smoke = clamp(d * uContrast + g, 0.0, 1.0);
        float hx = smoothstep(0.0, 0.15, uv.x) * (1.0 - smoothstep(0.85, 1.0, uv.x));
        smoke *= mix(0.95, 1.0, hx);

        vec3 tint = vec3(0.8, 0.85, 1.0);
        vec3 col = vec3(smoke) * tint;
        col = tonemap(col * 2.2);
        gl_FragColor = vec4(col, 1.0);
      }
    `;

    const uniforms = {
      iResolution: { value: new THREE.Vector2(window.innerWidth, window.innerHeight) },
      iTime:       { value: 0 },
      uDensity:    { value: 0.35 },
      uRise:       { value: 0.5 },
      uWind:       { value: 0.15 },
      uTurbulence: { value: 1.0 },
      uFill:       { value: 0.7 },
      uContrast:   { value: 0.7 },
      uGrain:      { value: 0.0 },
      uQuality:    { value: 0.65 },
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
  };

  schedule(start);
})();
