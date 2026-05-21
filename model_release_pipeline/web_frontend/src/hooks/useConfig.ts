import { useCallback, useEffect, useState } from 'react';
import {
  getConfigBranches,
  getLubanHosts,
  getOffboardTestYamls,
  getStageDefaults,
} from '../api/client';
import type {
  BranchInfo,
  LubanHostsResponse,
  StageConfig,
} from '../types/api';

export interface AppConfig {
  branches: BranchInfo[];
  lubanHosts: LubanHostsResponse | null;
  offboardTestYamls: string[];
  stageDefaults: StageConfig;
}

const INITIAL: AppConfig = {
  branches: [],
  lubanHosts: null,
  offboardTestYamls: [],
  stageDefaults: {},
};

export function useConfig() {
  const [config, setConfig] = useState<AppConfig>(INITIAL);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setLoading(true);
      const [branches, hosts, yamls, defaults] = await Promise.all([
        getConfigBranches().catch(() => ({ branches: [] as BranchInfo[] })),
        getLubanHosts().catch((): LubanHostsResponse | null => null),
        getOffboardTestYamls().catch(() => ({ source: '', yamls: [] as { name: string }[] })),
        getStageDefaults().catch(() => ({ stage_defaults: {} as StageConfig })),
      ]);
      setConfig({
        branches: branches.branches,
        lubanHosts: hosts,
        offboardTestYamls: yamls.yamls.map((y) => y.name),
        stageDefaults: defaults.stage_defaults,
      });
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  return { config, error, loading, refresh };
}
