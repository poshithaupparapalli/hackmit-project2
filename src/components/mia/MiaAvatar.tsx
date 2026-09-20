import { useEffect, useMemo, useState } from 'react';
import { motion, AnimatePresence, type TargetAndTransition } from 'framer-motion';
import type { MiaState } from './mia-personality';
import './mia-theme.css';

interface MiaAvatarProps {
  state: MiaState;
  size?: number;
}

/** Whimsy color for low-stakes states, competence color for trust-critical ones. */
const STATE_COLOR: Record<MiaState, string> = {
  idle: 'var(--mia-whimsy)',
  thinking: 'var(--mia-whimsy)',
  suggesting: 'var(--mia-whimsy)',
  confirming: 'var(--mia-competent)',
  running: 'var(--mia-competent)',
  success: 'var(--mia-competent)',
  failure: 'var(--mia-caution)',
};

export function MiaAvatar({ state, size = 96 }: MiaAvatarProps) {
  const [blink, setBlink] = useState(false);

  // Idle blink only during low-stakes states — confirming/running should
  // read as "paying attention," not fidgety.
  useEffect(() => {
    if (state !== 'idle' && state !== 'thinking') return;
    const id = setInterval(() => {
      setBlink(true);
      setTimeout(() => setBlink(false), 140);
    }, 3200 + Math.random() * 1800);
    return () => clearInterval(id);
  }, [state]);

  const bodyAnim = useMemo<TargetAndTransition>(() => {
    switch (state) {
      case 'idle':
        return { scale: [1, 1.03, 1], transition: { duration: 3.4, repeat: Infinity, ease: 'easeInOut' } };
      case 'thinking':
        return { rotate: [-2, 2, -2], transition: { duration: 1.6, repeat: Infinity, ease: 'easeInOut' } };
      case 'suggesting':
        return { scale: [1, 1.08, 1.04], y: [0, -4, -2], transition: { duration: 0.5, ease: 'easeOut' } };
      case 'confirming':
        // Deliberately the stillest state — reads as "paying attention."
        return { scale: 1, y: 0, rotate: 0, transition: { duration: 0.3, ease: 'easeOut' } };
      case 'running':
        return { scale: [1, 1.05, 1], transition: { duration: 0.9, repeat: Infinity, ease: 'easeInOut' } };
      case 'success':
        return { scale: [1, 1.18, 0.96, 1.05, 1], transition: { duration: 0.6, ease: 'easeOut' } };
      case 'failure':
        // Settles, doesn't slump — steady, not sad.
        return { y: [0, 3, 0], transition: { duration: 0.4, ease: 'easeOut' } };
      default:
        return {};
    }
  }, [state]);

  const eyeRy = blink ? 0.6 : state === 'confirming' ? 3.3 : 6;

  return (
    <div style={{ width: size, height: size }}>
      <motion.svg viewBox="0 0 100 100" width={size} height={size} animate={bodyAnim} style={{ transformOrigin: '50% 50%' }}>
        {/* Working ring — only while running */}
        <AnimatePresence>
          {state === 'running' && (
            <motion.circle
              key="ring"
              cx="50"
              cy="50"
              r="46"
              fill="none"
              stroke="var(--mia-competent-soft)"
              strokeWidth="3"
              strokeDasharray="18 10"
              initial={{ opacity: 0, rotate: 0 }}
              animate={{ opacity: 1, rotate: 360 }}
              exit={{ opacity: 0 }}
              transition={{ rotate: { duration: 2.4, repeat: Infinity, ease: 'linear' }, opacity: { duration: 0.2 } }}
              style={{ transformOrigin: '50% 50%' }}
            />
          )}
        </AnimatePresence>

        {/* Body */}
        <motion.circle cx="50" cy="50" r="38" animate={{ fill: STATE_COLOR[state] }} transition={{ duration: 0.4 }} />

        {/* Eyes */}
        <motion.ellipse cx="38" cy="48" rx="4.5" animate={{ ry: eyeRy }} fill="var(--mia-ink)" />
        <motion.ellipse cx="62" cy="48" rx="4.5" animate={{ ry: eyeRy }} fill="var(--mia-ink)" />

        {/* Mouth — the one feature that visibly carries emotional state */}
        {state === 'success' && (
          <path d="M40 60 Q50 68 60 60" stroke="var(--mia-ink)" strokeWidth="3" fill="none" strokeLinecap="round" />
        )}
        {state === 'failure' && (
          <path d="M42 61 Q50 58 58 61" stroke="var(--mia-ink)" strokeWidth="3" fill="none" strokeLinecap="round" />
        )}
        {(state === 'idle' || state === 'suggesting' || state === 'thinking') && (
          <path d="M42 60 Q50 64 58 60" stroke="var(--mia-ink)" strokeWidth="3" fill="none" strokeLinecap="round" />
        )}
        {state === 'confirming' && <line x1="43" y1="61" x2="57" y2="61" stroke="var(--mia-ink)" strokeWidth="3" strokeLinecap="round" />}
        {state === 'running' && <circle cx="50" cy="62" r="3" fill="var(--mia-ink)" />}

        {/* Success sparkle burst */}
        <AnimatePresence>
          {state === 'success' && (
            <motion.g
              key="sparkle"
              initial={{ opacity: 0, scale: 0.4 }}
              animate={{ opacity: [0, 1, 0], scale: [0.4, 1.1, 1.3] }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.7 }}
              style={{ transformOrigin: '50% 50%' }}
            >
              <circle cx="78" cy="26" r="3" fill="var(--mia-whimsy)" />
              <circle cx="22" cy="30" r="2" fill="var(--mia-whimsy)" />
              <circle cx="70" cy="76" r="2.5" fill="var(--mia-whimsy)" />
            </motion.g>
          )}
        </AnimatePresence>
      </motion.svg>
    </div>
  );
}
