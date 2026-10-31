import { pollVisible } from './liveView';

export function startVisiblePolling<T>(load: () => Promise<T | null>, refreshing: (value: T) => boolean = () => false) {
  return pollVisible(load, refreshing, {
    hidden: () => document.hidden,
    listen: callback => {
      document.addEventListener('visibilitychange', callback);
      return () => document.removeEventListener('visibilitychange', callback);
    },
    schedule: (callback, delay) => window.setTimeout(callback, delay),
    clear: timer => window.clearTimeout(timer as number),
  });
}
