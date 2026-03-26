(() => {
  if (window.__bgmWelderCursorInit) {
    return;
  }
  window.__bgmWelderCursorInit = true;

  const FINE_POINTER_MEDIA = window.matchMedia("(hover: hover) and (pointer: fine)");
  const REDUCED_MOTION_MEDIA = window.matchMedia("(prefers-reduced-motion: reduce)");
  const ROOT = document.documentElement;
  const INTERACTIVE_SELECTOR = [
    "a[href]",
    "button:not([disabled])",
    "input:not([type='hidden']):not([disabled])",
    "select:not([disabled])",
    "textarea:not([disabled])",
    "summary",
    "label[for]",
    "[role='button']",
    "[role='option']",
    "[tabindex]:not([tabindex='-1'])",
  ].join(",");
  const SURFACE_SELECTOR = [
    ".btn",
    ".card",
    ".product",
    ".cat",
    ".storefront-card",
    ".storefront-button",
    ".storefront-categoryCard",
    ".storefront-categoryPill",
    ".storefront-related__card",
    ".storefront-chip",
    ".bgm-topbar__brand",
    ".bgm-topbar__nav a",
    ".bgm-topbar__search",
    ".bgm-topbar__search-launch",
    ".bgm-search-overlay__close",
    ".contact-fab",
    ".contact-btn",
    ".filters-toggle",
    ".filters-toolbar__clear",
    ".store-pagination__btn",
    "input:not([type='hidden'])",
    "select",
    "textarea",
    "summary",
  ].join(",");

  let activeCursor = null;

  class WelderCursor {
    constructor() {
      this.reducedMotion = REDUCED_MOTION_MEDIA.matches;
      this.maxParticles = 128;
      this.particles = [];
      this.emitBudget = 0;
      this.hoverEnergy = 0;
      this.clickEnergy = 0;
      this.idleEnergy = 0;
      this.visible = false;
      this.currentSurface = null;
      this.currentInteractive = null;
      this.lastFrame = 0;
      this.nextIdleSparkAt = 0;
      this.pointerX = window.innerWidth * 0.5;
      this.pointerY = window.innerHeight * 0.5;
      this.renderX = this.pointerX;
      this.renderY = this.pointerY;
      this.velocityX = 0;
      this.velocityY = 0;
      this.lastPointerX = null;
      this.lastPointerY = null;
      this.rafId = 0;
      this.boundMove = this.onPointerMove.bind(this);
      this.boundLeave = this.onPointerLeave.bind(this);
      this.boundDown = this.onPointerDown.bind(this);
      this.boundUp = this.onPointerUp.bind(this);
      this.boundResize = this.onResize.bind(this);
      this.boundVisibility = this.onVisibilityChange.bind(this);
      this.boundTick = this.tick.bind(this);

      this.mount();
      this.attach();
      this.setReducedMotion(this.reducedMotion);
      this.onResize();
      ROOT.classList.add("bgm-welder-cursor-active");
      this.rafId = window.requestAnimationFrame(this.boundTick);
    }

    mount() {
      this.layer = document.createElement("div");
      this.layer.className = "bgm-welder-layer";
      this.layer.setAttribute("aria-hidden", "true");

      this.canvas = document.createElement("canvas");
      this.canvas.className = "bgm-welder-canvas";

      this.cursor = document.createElement("div");
      this.cursor.className = "bgm-welder-cursor";

      const core = document.createElement("div");
      core.className = "bgm-welder-cursor__core";

      const flare = document.createElement("div");
      flare.className = "bgm-welder-cursor__flare";

      this.cursor.append(core, flare);
      this.layer.append(this.canvas, this.cursor);
      document.body.append(this.layer);

      this.ctx = this.canvas.getContext("2d");
    }

    attach() {
      window.addEventListener("mousemove", this.boundMove, { passive: true });
      window.addEventListener("mousedown", this.boundDown, { passive: true });
      window.addEventListener("mouseup", this.boundUp, { passive: true });
      window.addEventListener("mouseleave", this.boundLeave, { passive: true });
      window.addEventListener("blur", this.boundLeave, { passive: true });
      window.addEventListener("resize", this.boundResize, { passive: true });
      window.addEventListener("orientationchange", this.boundResize, { passive: true });
      document.addEventListener("visibilitychange", this.boundVisibility, { passive: true });
    }

    detach() {
      window.removeEventListener("mousemove", this.boundMove);
      window.removeEventListener("mousedown", this.boundDown);
      window.removeEventListener("mouseup", this.boundUp);
      window.removeEventListener("mouseleave", this.boundLeave);
      window.removeEventListener("blur", this.boundLeave);
      window.removeEventListener("resize", this.boundResize);
      window.removeEventListener("orientationchange", this.boundResize);
      document.removeEventListener("visibilitychange", this.boundVisibility);
    }

    destroy() {
      this.detach();
      this.clearSurface();
      window.cancelAnimationFrame(this.rafId);
      ROOT.classList.remove("bgm-welder-cursor-active", "bgm-welder-cursor-reduced-motion");
      if (this.layer) {
        this.layer.remove();
      }
    }

    setReducedMotion(reducedMotion) {
      this.reducedMotion = reducedMotion;
      ROOT.classList.toggle("bgm-welder-cursor-reduced-motion", reducedMotion);
      if (reducedMotion) {
        this.particles.length = 0;
        this.emitBudget = 0;
        this.idleEnergy = 0;
      }
    }

    onResize() {
      this.dpr = Math.min(window.devicePixelRatio || 1, 2);
      const width = window.innerWidth;
      const height = window.innerHeight;

      this.canvas.width = Math.floor(width * this.dpr);
      this.canvas.height = Math.floor(height * this.dpr);
      this.canvas.style.width = `${width}px`;
      this.canvas.style.height = `${height}px`;
      this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    }

    onVisibilityChange() {
      if (document.hidden) {
        this.onPointerLeave();
      }
    }

    onPointerMove(event) {
      this.pointerX = event.clientX;
      this.pointerY = event.clientY;

      if (this.lastPointerX != null && this.lastPointerY != null) {
        this.velocityX = this.pointerX - this.lastPointerX;
        this.velocityY = this.pointerY - this.lastPointerY;

        const travel = Math.hypot(this.velocityX, this.velocityY);
        if (!this.reducedMotion && travel > 0.9) {
          const multiplier = this.currentInteractive ? 1.75 : 1.25;
          this.emitBudget += Math.min(5.4, travel / 10) * multiplier;
        }
      }

      this.lastPointerX = this.pointerX;
      this.lastPointerY = this.pointerY;

      if (!this.visible) {
        this.visible = true;
        this.cursor.style.opacity = "1";
      }

      const target = event.target instanceof Element ? event.target : null;
      this.updateHoverState(target);
    }

    onPointerLeave() {
      this.visible = false;
      this.cursor.style.opacity = "0";
      this.lastPointerX = null;
      this.lastPointerY = null;
      this.velocityX = 0;
      this.velocityY = 0;
      this.clearSurface();
      this.currentInteractive = null;
    }

    onPointerDown(event) {
      if (event.button !== 0) {
        return;
      }

      this.clickEnergy = 1;
      if (!this.reducedMotion) {
        this.spawnBurst(this.pointerX, this.pointerY, this.currentInteractive ? 22 : 16);
      }
    }

    onPointerUp() {
      this.clickEnergy = Math.max(this.clickEnergy, 0.24);
    }

    updateHoverState(target) {
      const interactive = this.closestMatch(target, INTERACTIVE_SELECTOR);
      const surface = this.closestMatch(target, SURFACE_SELECTOR) || interactive;

      this.currentInteractive = interactive;

      if (surface === this.currentSurface) {
        return;
      }

      this.clearSurface();
      this.currentSurface = surface;
      if (this.currentSurface) {
        this.currentSurface.classList.add("is-cursor-hot");
      }
    }

    clearSurface() {
      if (this.currentSurface) {
        this.currentSurface.classList.remove("is-cursor-hot");
        this.currentSurface = null;
      }
    }

    closestMatch(element, selector) {
      if (!element) {
        return null;
      }
      if (typeof element.closest === "function") {
        return element.closest(selector);
      }
      return null;
    }

    spawnBurst(x, y, count) {
      for (let index = 0; index < count; index += 1) {
        const angle = -Math.PI * 0.5 + (Math.random() - 0.5) * 1.9;
        const velocity = 2.4 + Math.random() * 5.2;
        this.pushParticle({
          x,
          y,
          vx: Math.cos(angle) * velocity + (Math.random() - 0.5) * 1.5,
          vy: Math.sin(angle) * velocity + Math.random() * 1.1,
          gravity: 0.085 + Math.random() * 0.09,
          drag: 0.974 - Math.random() * 0.012,
          size: 1.1 + Math.random() * 2,
          ttl: 135 + Math.random() * 175,
          hot: Math.random() < 0.26,
          hue: Math.random() < 0.28 ? 38 : 24 + Math.random() * 18,
        });
      }
    }

    spawnTrailParticle() {
      const travel = Math.hypot(this.velocityX, this.velocityY) || 1;
      const reverseAngle = Math.atan2(this.velocityY || 0.001, this.velocityX || 0.001) + Math.PI;
      const spread = 0.56 + Math.random() * 0.6;
      const angle = reverseAngle + (Math.random() - 0.5) * spread;
      const velocity = 1.15 + Math.random() * 2.2 + travel * 0.06;
      const hoverBoost = this.currentInteractive ? 1.28 : 1.05;

      this.pushParticle({
        x: this.renderX + (Math.random() - 0.5) * 4,
        y: this.renderY + (Math.random() - 0.5) * 4,
        vx: Math.cos(angle) * velocity * hoverBoost,
        vy: Math.sin(angle) * velocity * hoverBoost + Math.random() * 0.4,
        gravity: 0.055 + Math.random() * 0.05,
        drag: 0.976 - Math.random() * 0.008,
        size: 0.8 + Math.random() * 1.5,
        ttl: 105 + Math.random() * 145,
        hot: Math.random() < 0.18,
        hue: Math.random() < 0.24 ? 38 : 22 + Math.random() * 20,
      });
    }

    spawnIdleParticle() {
      const angle = Math.random() * Math.PI * 2;
      const distance = 4 + Math.random() * 7;
      const drift = angle - Math.PI * 0.5 + (Math.random() - 0.5) * 0.7;

      this.pushParticle({
        x: this.renderX + Math.cos(angle) * distance,
        y: this.renderY + Math.sin(angle) * distance,
        vx: Math.cos(drift) * (0.45 + Math.random() * 0.8),
        vy: Math.sin(drift) * (0.5 + Math.random() * 0.9),
        gravity: 0.02 + Math.random() * 0.02,
        drag: 0.987 - Math.random() * 0.004,
        size: 0.55 + Math.random() * 1.05,
        ttl: 140 + Math.random() * 160,
        hot: Math.random() < 0.34,
        hue: Math.random() < 0.2 ? 38 : 22 + Math.random() * 18,
      });
    }

    pushParticle(particle) {
      if (this.particles.length >= this.maxParticles) {
        this.particles.shift();
      }
      this.particles.push({
        ...particle,
        age: 0,
        previousX: particle.x,
        previousY: particle.y,
      });
    }

    tick(frameTime) {
      const delta = this.lastFrame ? Math.min(32, frameTime - this.lastFrame) : 16;
      this.lastFrame = frameTime;
      this.velocityX *= 0.88;
      this.velocityY *= 0.88;

      const lerp = this.currentInteractive ? 0.26 : 0.22;
      this.renderX += (this.pointerX - this.renderX) * lerp;
      this.renderY += (this.pointerY - this.renderY) * lerp;
      this.hoverEnergy += ((this.currentInteractive ? 1 : 0) - this.hoverEnergy) * 0.16;
      this.clickEnergy *= this.reducedMotion ? 0.72 : 0.83;
      const motionEnergy = Math.min(1, Math.hypot(this.velocityX, this.velocityY) / 10);
      const idleTarget = this.visible ? Math.max(0, 1 - motionEnergy) : 0;
      this.idleEnergy += (idleTarget - this.idleEnergy) * 0.08;
      if (this.clickEnergy < 0.02) {
        this.clickEnergy = 0;
      }

      if (!this.reducedMotion && this.visible) {
        const sparksThisFrame = Math.min(5, Math.floor(this.emitBudget));
        this.emitBudget = Math.max(0, this.emitBudget - sparksThisFrame);
        for (let index = 0; index < sparksThisFrame; index += 1) {
          this.spawnTrailParticle();
        }

        if (motionEnergy < 0.08 && frameTime >= this.nextIdleSparkAt) {
          this.spawnIdleParticle();
          if (Math.random() < 0.35) {
            this.spawnIdleParticle();
          }
          this.nextIdleSparkAt = frameTime + 110 + Math.random() * 160;
        }
      } else {
        this.emitBudget = 0;
        this.nextIdleSparkAt = frameTime + 160;
      }

      this.renderCursor();
      this.renderParticles(delta);
      this.rafId = window.requestAnimationFrame(this.boundTick);
    }

    renderCursor() {
      const scale = 1 + this.hoverEnergy * 0.22 + this.clickEnergy * 0.18 + this.idleEnergy * 0.04;
      this.cursor.style.setProperty("--bgm-cursor-energy", this.hoverEnergy.toFixed(3));
      this.cursor.style.setProperty("--bgm-cursor-engagement", this.hoverEnergy.toFixed(3));
      this.cursor.style.setProperty("--bgm-cursor-flash", this.clickEnergy.toFixed(3));
      this.cursor.style.setProperty("--bgm-cursor-idle", this.idleEnergy.toFixed(3));
      this.cursor.style.transform =
        `translate3d(${this.renderX}px, ${this.renderY}px, 0) translate(-50%, -50%) scale(${scale.toFixed(3)})`;
    }

    renderParticles(delta) {
      this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
      if (!this.particles.length) {
        return;
      }

      this.ctx.globalCompositeOperation = "lighter";

      for (let index = this.particles.length - 1; index >= 0; index -= 1) {
        const particle = this.particles[index];
        particle.age += delta;

        if (particle.age >= particle.ttl) {
          this.particles.splice(index, 1);
          continue;
        }

        particle.previousX = particle.x;
        particle.previousY = particle.y;

        particle.vx *= particle.drag;
        particle.vy = particle.vy * particle.drag + particle.gravity;
        particle.x += particle.vx * (delta / 16);
        particle.y += particle.vy * (delta / 16);

        const life = 1 - particle.age / particle.ttl;
        const strokeAlpha = particle.hot ? life * 0.92 : life * 0.75;
        const lightness = particle.hot ? 92 : 58 + life * 18;

        this.ctx.strokeStyle = `hsla(${particle.hue}, 100%, ${lightness}%, ${strokeAlpha})`;
        this.ctx.lineWidth = particle.size * life;
        this.ctx.lineCap = "round";
        this.ctx.beginPath();
        this.ctx.moveTo(particle.previousX, particle.previousY);
        this.ctx.lineTo(particle.x, particle.y);
        this.ctx.stroke();

        this.ctx.fillStyle = particle.hot
          ? `rgba(255, 248, 232, ${life * 0.6})`
          : `hsla(${particle.hue}, 100%, 66%, ${life * 0.32})`;
        this.ctx.beginPath();
        this.ctx.arc(particle.x, particle.y, particle.size * 0.38, 0, Math.PI * 2);
        this.ctx.fill();
      }

      this.ctx.globalCompositeOperation = "source-over";
    }
  }

  function syncCursorState() {
    if (FINE_POINTER_MEDIA.matches) {
      if (!activeCursor) {
        activeCursor = new WelderCursor();
      }
      return;
    }

    if (activeCursor) {
      activeCursor.destroy();
      activeCursor = null;
    }
  }

  function syncReducedMotion() {
    if (activeCursor) {
      activeCursor.setReducedMotion(REDUCED_MOTION_MEDIA.matches);
    }
  }

  FINE_POINTER_MEDIA.addEventListener("change", syncCursorState);
  REDUCED_MOTION_MEDIA.addEventListener("change", syncReducedMotion);
  syncCursorState();
})();
