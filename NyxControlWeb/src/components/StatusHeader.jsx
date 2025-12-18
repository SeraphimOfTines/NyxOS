import React from 'react';
import { Activity, Moon, Zap, Power } from 'lucide-react';
import { setGlobalState } from '../api';

export default function StatusHeader({ status, latency, user }) {
  const isOnline = status === 'online';

  const handleAction = async (action) => {
    try {
      await setGlobalState(action);
    } catch (err) {
      console.error("Failed to set state:", err);
    }
  };

  return (
    <div className="bg-discord-dark p-4 rounded-lg shadow-lg mb-6 flex items-center justify-between border border-discord-darker">
      {/* Status */}
      <div className="flex items-center space-x-4">
        <div className={`w-4 h-4 rounded-full ${isOnline ? 'bg-discord-green shadow-[0_0_10px_#57F287]' : 'bg-discord-red shadow-[0_0_10px_#ED4245]'}`} />
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
             {isOnline ? `Connected: ${user}` : "Disconnected"}
          </h2>
          <p className="text-xs text-gray-400 font-mono">Latency: {latency}ms</p>
        </div>
      </div>

      {/* Global Controls */}
      <div className="flex items-center space-x-2">
        <button 
          onClick={() => handleAction('awake')}
          className="flex items-center gap-2 px-4 py-2 bg-discord-blurple hover:bg-indigo-500 rounded text-white font-bold transition-all active:scale-95"
        >
          <Zap size={18} /> Awake
        </button>
        <button 
          onClick={() => handleAction('idle')}
          className="flex items-center gap-2 px-4 py-2 bg-yellow-600 hover:bg-yellow-500 rounded text-white font-bold transition-all active:scale-95"
        >
          <Activity size={18} /> Idle
        </button>
        <button 
          onClick={() => handleAction('sleep')}
          className="flex items-center gap-2 px-4 py-2 bg-discord-red hover:bg-red-500 rounded text-white font-bold transition-all active:scale-95"
        >
          <Moon size={18} /> Sleep
        </button>
      </div>
    </div>
  );
}
