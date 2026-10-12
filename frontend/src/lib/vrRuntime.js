/** WebXR / OpenXR enter path for Heirloom Room sit. */

import { areaAlongRay } from "./vrGaze";
import { readSessionPtt, TWIN_SEAT } from "./vrTalk";
import { coachHref, headsetHintFromUa, VR_SETUP_PATH } from "./vrCompat";

export const ENTER_CODES = {
  ok: "ok",
  insecure: "insecure",
  no_webxr: "no_webxr",
  no_headset: "no_headset",
  no_webgl: "no_webgl",
  refused: "refused",
  no_gesture: "no_gesture",
};

export { TWIN_SEAT };

function defaultNav() {
  return typeof navigator !== "undefined" ? navigator : undefined;
}

function defaultWin() {
  return typeof window !== "undefined" ? window : undefined;
}

export async function probeBrowserXr(nav = defaultNav(), win = defaultWin()) {
  const secure = Boolean(win?.isSecureContext);
  const xr = nav?.xr;
  let immersiveVr = false;
  if (xr && typeof xr.isSessionSupported === "function") {
    try {
      immersiveVr = Boolean(await xr.isSessionSupported("immersive-vr"));
    } catch {
      immersiveVr = false;
    }
  }
  const ua = nav?.userAgent || "";
  return {
    secure,
    hasXr: Boolean(xr),
    immersiveVr,
    userAgent: ua,
    headsetHint: headsetHintFromUa(ua),
  };
}

export function describeEnterFailure(probe, extra = {}) {
  const hint = probe?.headsetHint;
  const base = { coachPath: coachHref(hint?.id), headsetHint: hint, ...extra };
  if (!probe?.secure) {
    return {
      ok: false,
      code: ENTER_CODES.insecure,
      reason: "This page is not a secure context. Open Heirloom on https:// or http://localhost.",
      ...base,
    };
  }
  if (!probe?.hasXr) {
    return {
      ok: false,
      code: ENTER_CODES.no_webxr,
      reason: "This browser does not expose WebXR. On a Quest, use the headset browser. On a PC, use Chrome or Edge after SteamVR / Link is running.",
      ...base,
    };
  }
  if (!probe?.immersiveVr) {
    return {
      ok: false,
      code: ENTER_CODES.no_headset,
      reason: "No immersive VR headset is available. Install the free runtime for your headset, or open the VR setup coach.",
      ...base,
    };
  }
  return null;
}

export function openXrSelfCheck(probe, serverProbe) {
  const items = [
    {
      id: "https",
      ok: Boolean(probe?.secure),
      label: "Secure context (HTTPS or localhost)",
    },
    {
      id: "webxr_api",
      ok: Boolean(probe?.hasXr),
      label: "Browser exposes navigator.xr",
    },
    {
      id: "immersive_vr",
      ok: Boolean(probe?.immersiveVr),
      label: "immersive-vr is supported right now",
    },
    {
      id: "runtime_json",
      ok: serverProbe?.openxr?.found ?? null,
      label: serverProbe?.openxr?.found
        ? `Active OpenXR runtime: ${serverProbe.openxr.runtime_name || "found"}`
        : "Active OpenXR runtime file (this PC)",
      detail: serverProbe?.openxr?.runtime_path || serverProbe?.openxr?.hint,
    },
  ];
  return items;
}

function compileShader(gl, type, src) {
  const sh = gl.createShader(type);
  gl.shaderSource(sh, src);
  gl.compileShader(sh);
  return sh;
}

function makeRoomProgram(gl) {
  const vs = compileShader(
    gl,
    gl.VERTEX_SHADER,
    `
    attribute vec3 aPos;
    uniform mat4 uView;
    uniform mat4 uProj;
    varying float vShade;
    void main() {
      vShade = 0.35 + aPos.y * 0.2;
      gl_Position = uProj * uView * vec4(aPos, 1.0);
    }
  `,
  );
  const fs = compileShader(
    gl,
    gl.FRAGMENT_SHADER,
    `
    precision mediump float;
    varying float vShade;
    uniform vec3 uTint;
    void main() {
      gl_FragColor = vec4(uTint * vShade, 1.0);
    }
  `,
  );
  const prog = gl.createProgram();
  gl.attachShader(prog, vs);
  gl.attachShader(prog, fs);
  gl.linkProgram(prog);
  return prog;
}

function identity() {
  return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
}

function fromXRRigid(transform) {
  const m = transform?.matrix;
  if (m && m.length === 16) return Array.from(m);
  return identity();
}

function invertRigid(m) {
  const out = identity();
  out[0] = m[0];
  out[1] = m[4];
  out[2] = m[8];
  out[4] = m[1];
  out[5] = m[5];
  out[6] = m[9];
  out[8] = m[2];
  out[9] = m[6];
  out[10] = m[10];
  out[12] = -(m[12] * out[0] + m[13] * out[4] + m[14] * out[8]);
  out[13] = -(m[12] * out[1] + m[13] * out[5] + m[14] * out[9]);
  out[14] = -(m[12] * out[2] + m[13] * out[6] + m[14] * out[10]);
  return out;
}

function perspectiveFromFov(fov, near, far) {
  const up = Math.tan(fov.upDegrees * Math.PI / 180);
  const down = Math.tan(fov.downDegrees * Math.PI / 180);
  const left = Math.tan(fov.leftDegrees * Math.PI / 180);
  const right = Math.tan(fov.rightDegrees * Math.PI / 180);
  const x = 2 / (left + right);
  const y = 2 / (up + down);
  const out = identity();
  out[0] = x;
  out[5] = y;
  out[8] = (left - right) * x * 0.5;
  out[9] = (up - down) * y * 0.5;
  out[10] = far / (near - far);
  out[11] = -1;
  out[14] = (far * near) / (near - far);
  out[15] = 0;
  return out;
}

function cuboid(x0, y0, z0, x1, y1, z1) {
  return [
    x0, y0, z0, x1, y0, z0, x1, y0, z1, x0, y0, z0, x1, y0, z1, x0, y0, z1,
    x0, y1, z0, x1, y1, z0, x1, y1, z1, x0, y1, z0, x1, y1, z1, x0, y1, z1,
    x0, y0, z1, x1, y0, z1, x1, y1, z1, x0, y0, z1, x1, y1, z1, x0, y1, z1,
    x0, y0, z0, x0, y1, z0, x1, y1, z0, x0, y0, z0, x1, y1, z0, x1, y0, z0,
    x0, y0, z0, x0, y0, z1, x0, y1, z1, x0, y0, z0, x0, y1, z1, x0, y1, z0,
    x1, y0, z1, x1, y0, z0, x1, y1, z0, x1, y0, z1, x1, y1, z0, x1, y1, z1,
  ];
}

function twinFigureVertices() {
  // A seated block figure across the table. Not a face, not a likeness mesh.
  const seat = cuboid(-0.35, 0.42, -1.95, 0.35, 0.52, -1.25);
  const torso = cuboid(-0.22, 0.52, -1.78, 0.22, 1.12, -1.42);
  const head = cuboid(-0.12, 1.12, -1.72, 0.12, 1.4, -1.48);
  return new Float32Array([...seat, ...torso, ...head]);
}

function rayFromViewMatrix(matrix) {
  if (!matrix || matrix.length < 16) return null;
  return {
    origin: [matrix[12], matrix[13], matrix[14]],
    direction: [-matrix[8], -matrix[9], -matrix[10]],
  };
}

function boxVertices() {
  const x = 2;
  const y0 = 0;
  const y1 = 2.4;
  const z = 2;
  const faces = [
    [-x, y0, -z, x, y0, -z, x, y0, z, -x, y0, -z, x, y0, z, -x, y0, z],
    [-x, y0, -z, x, y0, -z, x, y1, -z, -x, y0, -z, x, y1, -z, -x, y1, -z],
    [x, y0, -z, x, y0, z, x, y1, z, x, y0, -z, x, y1, z, x, y1, -z],
    [-x, y0, z, -x, y0, -z, -x, y1, -z, -x, y0, z, -x, y1, -z, -x, y1, z],
    [-x, y0, z, x, y0, z, x, y1, z, -x, y0, z, x, y1, z, -x, y1, z],
  ];
  const out = [];
  faces.forEach((f) => out.push(...f));
  return new Float32Array(out);
}

/**
 * Start an immersive-vr WebXR session. Refuses unless `gesture` is true so a
 * page load cannot enter the headset. The twin is a seated block across the
 * table. Eye gaze is optional and never required to start the session.
 * OpenXR-native WinUI viewing is deferred; on PC this is WebXR riding the active runtime.
 */
export async function enterRoomVr({ xr, win, gesture = false, gaze = false, onPtt, onAttention, onEnd } = {}) {
  if (!gesture) {
    return {
      ok: false,
      code: ENTER_CODES.no_gesture,
      session: null,
      gazeAvailable: false,
      reason: "VR stays on the normal screen until you turn it on.",
    };
  }
  const navXr = xr || defaultNav()?.xr;
  const probe = await probeBrowserXr(xr ? { xr, userAgent: defaultNav()?.userAgent } : defaultNav(), win || defaultWin());
  const fail = describeEnterFailure(probe);
  if (fail) return fail;
  if (!navXr?.requestSession) {
    return describeEnterFailure({ ...probe, hasXr: false });
  }

  const canvas = (win || defaultWin())?.document?.createElement?.("canvas") || null;
  let gl = null;
  try {
    gl = canvas?.getContext?.("webgl", { xrCompatible: true, alpha: false }) || null;
  } catch {
    gl = null;
  }
  if (!gl) {
    return {
      ok: false,
      code: ENTER_CODES.no_webgl,
      reason: "WebGL is required for the VR view. Try Chrome or Edge.",
      coachPath: VR_SETUP_PATH,
    };
  }

  try {
    if (typeof gl.makeXRCompatible === "function") await gl.makeXRCompatible();
    const session = await navXr.requestSession("immersive-vr", { optionalFeatures: ["local-floor"] });
    let gazeSpace = null;
    if (gaze && typeof session.requestReferenceSpace === "function") {
      try {
        gazeSpace = await session.requestReferenceSpace("gaze");
      } catch {
        gazeSpace = null;
      }
    }
    const host = win || defaultWin();
    const keys = new Set();
    const onKeyDown = (event) => {
      const tag = event.target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || event.repeat) return;
      if (event.code === "Space" || event.code === "KeyV") keys.add(event.code);
    };
    const onKeyUp = (event) => keys.delete(event.code);
    host?.addEventListener?.("keydown", onKeyDown);
    host?.addEventListener?.("keyup", onKeyUp);
    let closed = false;
    let pttWas = false;
    const finish = () => {
      if (closed) return;
      closed = true;
      keys.clear();
      host?.removeEventListener?.("keydown", onKeyDown);
      host?.removeEventListener?.("keyup", onKeyUp);
      onEnd?.({ gazeAvailable: Boolean(gazeSpace) });
    };
    session.addEventListener?.("end", finish);

    const Layer = host?.XRWebGLLayer;
    if (Layer) {
      const layer = new Layer(session, gl);
      await session.updateRenderState({ baseLayer: layer });
      const space = await session.requestReferenceSpace("local-floor").catch(() =>
        session.requestReferenceSpace("local"),
      );
      const prog = makeRoomProgram(gl);
      const buf = gl.createBuffer();
      const roomVerts = boxVertices();
      const twinVerts = twinFigureVertices();
      const verts = new Float32Array(roomVerts.length + twinVerts.length);
      verts.set(roomVerts, 0);
      verts.set(twinVerts, roomVerts.length);
      const roomCount = roomVerts.length / 3;
      const twinCount = twinVerts.length / 3;
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, verts, gl.STATIC_DRAW);
      const aPos = gl.getAttribLocation(prog, "aPos");
      const uView = gl.getUniformLocation(prog, "uView");
      const uProj = gl.getUniformLocation(prog, "uProj");
      const uTint = gl.getUniformLocation(prog, "uTint");

      const onFrame = (_time, frame) => {
        if (closed) return;
        session.requestAnimationFrame(onFrame);
        const pose = frame.getViewerPose(space);
        const base = session.renderState.baseLayer;
        const down = readSessionPtt(session, keys);
        if (down !== pttWas) {
          pttWas = down;
          onPtt?.({ phase: down ? "down" : "up" });
        }
        if (gazeSpace && onAttention) {
          const gazePose = frame.getPose?.(gazeSpace, space);
          const ray = rayFromViewMatrix(gazePose?.transform?.matrix);
          if (ray) {
            const area = areaAlongRay(ray.origin, ray.direction);
            if (area) onAttention({ area, time: _time });
          }
        }
        if (!pose || !base) return;
        gl.bindFramebuffer(gl.FRAMEBUFFER, base.framebuffer);
        gl.clearColor(0.07, 0.066, 0.062, 1);
        gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
        gl.enable(gl.DEPTH_TEST);
        gl.useProgram(prog);
        gl.bindBuffer(gl.ARRAY_BUFFER, buf);
        gl.enableVertexAttribArray(aPos);
        gl.vertexAttribPointer(aPos, 3, gl.FLOAT, false, 0, 0);
        for (const view of pose.views) {
          const vp = base.getViewport(view);
          gl.viewport(vp.x, vp.y, vp.width, vp.height);
          const viewMat = invertRigid(fromXRRigid(view.transform));
          const proj = view.projectionMatrix
            ? Array.from(view.projectionMatrix)
            : perspectiveFromFov(view.projection?.fov || view, 0.1, 40);
          gl.uniformMatrix4fv(uView, false, viewMat);
          gl.uniformMatrix4fv(uProj, false, proj);
          if (uTint) gl.uniform3f(uTint, 0.55, 0.42, 0.3);
          gl.drawArrays(gl.TRIANGLES, 0, roomCount);
          if (uTint) gl.uniform3f(uTint, 0.78, 0.58, 0.32);
          gl.drawArrays(gl.TRIANGLES, roomCount, twinCount);
        }
      };
      session.requestAnimationFrame(onFrame);
    }
    const end = () => {
      try {
        session.end?.();
      } catch {
        finish();
      }
    };
    return {
      ok: true,
      code: ENTER_CODES.ok,
      session,
      canvas,
      end,
      gazeAvailable: Boolean(gazeSpace),
      twinSeat: { ...TWIN_SEAT },
      runtime: "webxr",
      reason: "WebXR session started (OpenXR-backed on PC when a runtime is installed).",
    };
  } catch (err) {
    return {
      ok: false,
      code: ENTER_CODES.refused,
      reason: err?.message || "WebXR session was refused.",
      coachPath: coachHref(probe.headsetHint?.id),
    };
  }
}

export async function tryEnterWebXR(canvas, { gesture = false } = {}) {
  // Back-compat wrapper. Still requires a user gesture before a session starts.
  void canvas;
  return enterRoomVr({ gesture });
}
