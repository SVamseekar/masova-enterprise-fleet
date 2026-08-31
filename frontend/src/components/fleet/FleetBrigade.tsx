import { Grid, Html, Line, OrbitControls } from "@react-three/drei";
import { Canvas, useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { Badge } from "@/components/ui/badge";
import type { Agent } from "@/lib/masova-data";

const tierClass: Record<Agent["tier"], string> = {
  "Read / Compute": "border-emerald/30 bg-emerald/10 text-emerald",
  Propose: "border-primary/30 bg-primary/10 text-primary",
  "Execute (blocked)": "border-destructive/30 bg-destructive/10 text-destructive",
};

export const STATION: Record<string, string> = {
  "manager-copilot": "Expeditor",
  "demand-forecaster": "Garde-manger",
  "inventory-watcher": "Cellar",
  "churn-prevention": "Front of house",
  "review-responder": "Guest book",
  "shift-optimizer": "Roster",
  "kitchen-coach": "The pass",
  "dynamic-pricing": "The board",
};

const RADIUS = 3.35;

function stationPos(i: number, count: number) {
  const angle = (i / count) * Math.PI * 2 - Math.PI / 2;
  return new THREE.Vector3(Math.cos(angle) * RADIUS, 0.15, Math.sin(angle) * RADIUS);
}

function Packet({ from, to, delay }: { from: THREE.Vector3; to: THREE.Vector3; delay: number }) {
  const ref = useRef<THREE.Mesh>(null);
  useFrame(({ clock }) => {
    const mesh = ref.current;
    if (!mesh) return;
    const t = ((clock.elapsedTime + delay) % 6.2) / 6.2;
    const e = t * t * (3 - 2 * t);
    mesh.position.lerpVectors(from, to, e);
    mesh.visible = t > 0.05 && t < 0.9;
    const s = t < 0.12 || t > 0.82 ? 0.4 : 1;
    mesh.scale.setScalar(s);
  });
  return (
    <mesh ref={ref}>
      <sphereGeometry args={[0.05, 16, 16]} />
      <meshStandardMaterial
        color="#f0a14a"
        emissive="#f0a14a"
        emissiveIntensity={2.4}
        toneMapped={false}
      />
    </mesh>
  );
}

function StationCard({
  agent,
  position,
  hovered,
  onHover,
  onSelect,
}: {
  agent: Agent;
  position: THREE.Vector3;
  hovered: boolean;
  onHover: (id: string | null) => void;
  onSelect: (agent: Agent) => void;
}) {
  return (
    <group position={position}>
      <Html
        transform
        sprite
        distanceFactor={2.85}
        position={[0, 0.55, 0]}
        portal={false}
        zIndexRange={[20, 0]}
        style={{ pointerEvents: "auto" }}
      >
          <button
            type="button"
            onMouseEnter={() => onHover(agent.id)}
            onMouseLeave={() => onHover(null)}
            onFocus={() => onHover(agent.id)}
            onBlur={() => onHover(null)}
            onClick={() => onSelect(agent)}
            aria-label={`Open ${agent.name} details`}
            className={`glass-ticket w-44 rounded-2xl p-3 text-left transition-[border-color,box-shadow] ${
              hovered ? "border-primary/70 shadow-[0_0_28px_-6px_rgba(240,161,74,0.75)]" : ""
            }`}
          >
            <p className="font-mono text-[9px] uppercase tracking-[0.16em] text-primary">
              {STATION[agent.id]}
            </p>
            <span className="mt-2 grid size-8 place-items-center rounded-lg bg-[image:var(--gradient-primary)] text-primary-foreground">
              <agent.icon className="size-4" />
            </span>
            <h3 className="mt-2 text-sm font-semibold leading-tight">{agent.name}</h3>
            <p className="mt-1 text-[11px] leading-snug text-zinc-400">{agent.role}</p>
            <Badge variant="outline" className={`mt-2 w-fit text-[10px] ${tierClass[agent.tier]}`}>
              {agent.tier === "Propose" ? "Drafts only" : agent.tier}
            </Badge>
          </button>
      </Html>
    </group>
  );
}

function Scene({
  specialists,
  copilot,
  hovered,
  onHover,
  onSelect,
}: {
  specialists: Agent[];
  copilot: Agent;
  hovered: string | null;
  onHover: (id: string | null) => void;
  onSelect: (agent: Agent) => void;
}) {
  const reduce =
    typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const origin = useMemo(() => new THREE.Vector3(0, 0.2, 0), []);
  const points = useMemo(
    () => specialists.map((_, i) => stationPos(i, Math.max(specialists.length, 1))),
    [specialists]
  );

  return (
    <>
      <color attach="background" args={["#09090b"]} />
      <fog attach="fog" args={["#09090b", 10, 24]} />
      <ambientLight intensity={0.28} />
      <spotLight
        position={[5, 9, 4]}
        angle={0.38}
        penumbra={0.85}
        intensity={2.1}
        color="#f7be7b"
        castShadow
      />
      <spotLight position={[-7, 6, -3]} angle={0.5} intensity={0.55} color="#8aa4c8" />
      <pointLight position={[0, 1.4, 0]} intensity={1.6} color="#f0a14a" distance={9} />

      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -1.05, 0]} receiveShadow>
        <circleGeometry args={[7.2, 72]} />
        <meshStandardMaterial color="#0b0b0d" metalness={0.72} roughness={0.38} />
      </mesh>
      <Grid
        args={[12, 12]}
        cellSize={0.45}
        cellThickness={0.45}
        sectionSize={2.25}
        sectionThickness={0.9}
        cellColor="#2a2418"
        sectionColor="#4a3a22"
        fadeDistance={16}
        fadeFrom={0.6}
        position={[0, -1.04, 0]}
      />

      <mesh rotation={[Math.PI / 2, 0, 0]} position={[0, -0.02, 0]}>
        <torusGeometry args={[RADIUS, 0.012, 12, 160]} />
        <meshStandardMaterial
          color="#f0a14a"
          emissive="#f0a14a"
          emissiveIntensity={0.55}
          metalness={0.9}
          roughness={0.25}
        />
      </mesh>

      {points.map((p, i) => (
        <Line
          key={`spoke-${specialists[i]!.id}`}
          points={[origin.toArray(), p.toArray()]}
          color="#f0a14a"
          lineWidth={hovered === specialists[i]!.id ? 1.6 : 0.7}
          transparent
          opacity={hovered === specialists[i]!.id ? 0.85 : 0.28}
        />
      ))}

      {!reduce &&
        points.map((p, i) => (
          <Packet key={`pkt-${specialists[i]!.id}`} from={p} to={origin} delay={i * 0.85} />
        ))}

      {specialists.map((agent, i) => (
        <StationCard
          key={agent.id}
          agent={agent}
          position={points[i]!}
          hovered={hovered === agent.id}
          onHover={onHover}
          onSelect={onSelect}
        />
      ))}

      <Html
        transform
        sprite
        distanceFactor={3.05}
        position={[0, 0.72, 0]}
        portal={false}
        zIndexRange={[40, 0]}
        style={{ pointerEvents: "auto" }}
      >
          <button
            type="button"
            onClick={() => onSelect(copilot)}
            aria-label={`Open ${copilot.name} details`}
            className="glass-ticket w-48 rounded-2xl p-4 text-left"
          >
            <div className="flex items-center gap-2">
              <span className="pulse-dot size-1.5 rounded-full bg-emerald" />
              <p className="font-mono text-[9px] uppercase tracking-[0.16em] text-emerald">
                {STATION[copilot.id]} · live
              </p>
            </div>
            <span className="mt-3 grid size-11 place-items-center rounded-xl bg-[image:var(--gradient-primary)] text-primary-foreground">
              <copilot.icon className="size-5" />
            </span>
            <h3 className="mt-3 font-display text-lg font-semibold leading-tight">{copilot.name}</h3>
            <p className="mt-1 text-[12px] text-zinc-400">Tickets arrive here. A manager decides.</p>
          </button>
      </Html>

      <OrbitControls
        makeDefault
        enablePan={false}
        enableZoom={false}
        autoRotate={!reduce}
        autoRotateSpeed={0.45}
        target={[0, 0.2, 0]}
        minPolarAngle={Math.PI / 3.15}
        maxPolarAngle={Math.PI / 2.35}
        minDistance={8.5}
        maxDistance={12}
      />
    </>
  );
}

export function FleetBrigade(props: {
  specialists: Agent[];
  copilot: Agent;
  hovered: string | null;
  onHover: (id: string | null) => void;
  onSelect: (agent: Agent) => void;
}) {
  return (
    <div className="relative h-[38rem] w-full overflow-hidden rounded-2xl sm:h-[44rem]">
      <Canvas
        dpr={[1, 1.6]}
        gl={{ antialias: true, alpha: true }}
        camera={{ position: [0, 4.2, 9.2], fov: 36 }}
        onCreated={({ gl }) => {
          gl.setClearColor("#09090b", 0);
        }}
      >
        <Scene {...props} />
      </Canvas>
      <p className="pointer-events-none absolute bottom-3 left-1/2 -translate-x-1/2 font-mono text-[10px] uppercase tracking-[0.16em] text-zinc-500">
        Drag to inspect the pass
      </p>
    </div>
  );
}
