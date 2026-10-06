import { useEffect, useRef } from 'react';

// Анимированный фон: плавные цветные волны на WebGL (собственная реализация, без зависимостей).
const VERT = `attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}`;
const FRAG = `
precision mediump float;
uniform vec2 uRes;uniform float uTime;
uniform vec3 uBg;uniform vec3 uA;uniform vec3 uB;uniform vec3 uC;
void main(){
  vec2 uv=(gl_FragCoord.xy*2.-uRes)/min(uRes.x,uRes.y);
  float t=uTime;
  for(float i=1.;i<4.;i++){
    uv.x+=.55/i*sin(i*1.7*uv.y+t*.35+i*1.3);
    uv.y+=.55/i*cos(i*1.5*uv.x+t*.3+i*.7);
  }
  float m=.5+.5*sin(uv.x*1.2+uv.y*1.1+t*.2);
  float n=.5+.5*cos(uv.y*1.4-uv.x*.8-t*.15);
  vec3 col=mix(uA,uB,m);
  col=mix(col,uC,n*.55);
  float vig=smoothstep(2.4,.2,length((gl_FragCoord.xy/uRes-.5)*vec2(1.6,1.)));
  gl_FragColor=vec4(mix(uBg,col,vig),1.);
}`;

const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);

const LAGOON = ['#12b5c3', '#7fe1dc', '#ffffff'];

export default function ColorBends({ colors = LAGOON, bg = '#e9fbfa', speed = 1, className = '' }) {
  const ref = useRef(null);

  useEffect(() => {
    const canvas = ref.current;
    const gl = canvas.getContext('webgl', { antialias: false, alpha: false });
    if (!gl) return;

    const compile = (type, src) => {
      const s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      return s;
    };
    const prog = gl.createProgram();
    gl.attachShader(prog, compile(gl.VERTEX_SHADER, VERT));
    gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return;
    gl.useProgram(prog);

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, 'p');
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

    const u = (n) => gl.getUniformLocation(prog, n);
    const [a, b, c] = colors.map(hex);
    gl.uniform3fv(u('uBg'), hex(bg));
    gl.uniform3fv(u('uA'), a);
    gl.uniform3fv(u('uB'), b);
    gl.uniform3fv(u('uC'), c);

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5) * 0.6; // фон размытый, высокое разрешение не нужно
      canvas.width = Math.max(1, Math.floor(canvas.clientWidth * dpr));
      canvas.height = Math.max(1, Math.floor(canvas.clientHeight * dpr));
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.uniform2f(u('uRes'), canvas.width, canvas.height);
    };
    resize();
    window.addEventListener('resize', resize);

    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let raf = 0, visible = true;
    const t0 = performance.now();
    const draw = (now) => {
      gl.uniform1f(u('uTime'), reduce ? 4 : ((now - t0) / 1000) * speed);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      if (!reduce && visible) raf = requestAnimationFrame(draw);
    };
    draw(performance.now());

    const io = new IntersectionObserver(([e]) => {
      visible = e.isIntersecting;
      cancelAnimationFrame(raf);
      if (visible && !reduce) raf = requestAnimationFrame(draw);
    });
    io.observe(canvas);

    return () => {
      cancelAnimationFrame(raf);
      io.disconnect();
      window.removeEventListener('resize', resize);
    };
  }, [colors, bg, speed]);

  return <canvas ref={ref} className={'bends ' + className} aria-hidden="true" />;
}
