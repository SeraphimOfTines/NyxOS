import React, { useState, useEffect, useRef } from 'react';
import { checkStatus, getEmojis, syncEmojis, getPalette, savePalette, setGlobalState, updateGlobalText, getBars } from './api';
import { RefreshCw, Power, Eye, EyeOff, Save, Trash2, Zap, GripVertical } from 'lucide-react';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  DragOverlay,
  defaultDropAnimationSideEffects,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  rectSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';

// --- DRAGGABLE EMOJI COMPONENT ---
const SortableEmoji = ({ id, emoji, onClick, disabled }) => {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id, disabled });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0 : 1,
    touchAction: 'none', // Prevent scrolling while dragging
  };

  const isAnimated = emoji?.animated;
  const src = emoji?.url; 

  if (!emoji) return null;

  return (
    <div
      ref={setNodeRef}
      style={style}
      className="relative group w-12 h-12"
      {...attributes}
      {...listeners}
    >
      <button 
        onClick={(e) => {
            // Prevent click if we were dragging (dnd-kit handles this usually, but safe to check)
            if (!isDragging) onClick(emoji);
        }}
        className="w-full h-full p-2 hover:bg-gray-700 rounded transition-colors flex items-center justify-center cursor-grab active:cursor-grabbing"
        title={emoji.name}
      >
        <img 
          src={src} 
          alt={emoji.name} 
          className="w-8 h-8 object-contain pointer-events-none select-none" 
          loading="lazy"
        />
      </button>
    </div>
  );
};

// --- APP COMPONENT ---
function App() {
  // --- STATE ---
  const [status, setStatus] = useState({ status: 'offline', latency: 0 });
  const [inputText, setInputText] = useState("");
  const [emojis, setEmojis] = useState([]); // All emojis list
  const [palette, setPalette] = useState({ categories: {}, hidden: [] });
  const [isSyncing, setIsSyncing] = useState(false);
  const [activeTab, setActiveTab] = useState("quick"); // 'quick' or 'storage'
  const [activeDragId, setActiveDragId] = useState(null);

  // Sensors for DnD
  const sensors = useSensors(
    useSensor(PointerSensor, {
        activationConstraint: { distance: 5 } // Require 5px movement to start drag (allows clicks)
    }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  // --- INITIALIZATION ---
  useEffect(() => {
    // Poll Status every 2s
    const statusInterval = setInterval(fetchStatus, 2000);
    fetchStatus();
    fetchData();

    return () => clearInterval(statusInterval);
  }, []);

  const fetchStatus = async () => {
    try {
      const resp = await checkStatus();
      setStatus(resp.data);
    } catch (e) {
      setStatus({ status: 'offline', latency: 0, error: e.message });
    }
  };

  const fetchData = async () => {
    try {
      // 1. Get Emojis
      const emoResp = await getEmojis();
      setEmojis(emoResp.data.emojis || []);

      // 2. Get Palette
      const palResp = await getPalette();
      const pData = palResp.data;
      // Ensure structure
      const newPalette = {
        categories: pData.categories || { "Yami": [], "Calyptra": [], "Riven": [], "SΛTVRN": [], "Other": [] },
        hidden: pData.hidden || []
      };
      setPalette(newPalette);
      
      // 3. Get Current Text (Optimistic)
      const barsResp = await getBars();
      if (barsResp.data.global_content) {
          setInputText(barsResp.data.global_content);
      }

    } catch (e) {
      console.error("Init failed:", e);
    }
  };

  // --- PERSISTENCE ---
  const handleSavePalette = async (newPaletteState) => {
      setPalette(newPaletteState); // Optimistic Update
      try {
          // Flatten for API: categories + hidden
          const payload = {
              categories: newPaletteState.categories,
              hidden: newPaletteState.hidden,
              use_counts: {} // Preserve if we tracked it, but we don't right now
          };
          await savePalette(payload);
      } catch (e) {
          console.error("Failed to save palette:", e);
          alert("Failed to save order.");
      }
  };

  const handleSync = async () => {
    setIsSyncing(true);
    try {
      await syncEmojis();
      await fetchData();
      alert("Emojis synced successfully!");
    } catch (e) {
      alert("Sync Error: " + e.message);
    }
    setIsSyncing(false);
  };

  // --- DRAG HANDLERS ---
  const handleDragStart = (event) => {
      setActiveDragId(event.active.id);
  };

  const handleDragEnd = (event) => {
      const { active, over } = event;
      setActiveDragId(null);

      if (!over) return;

      const activeId = active.id;
      const overId = over.id;

      // Find containers
      const findContainer = (id) => {
          if (id in palette.categories) return id;
          if (id === 'hidden') return 'hidden';
          
          // Search inside
          for (const cat in palette.categories) {
              if (palette.categories[cat].includes(id)) return cat;
          }
          if (palette.hidden.includes(id)) return 'hidden';
          return null;
      };

      const activeContainer = findContainer(activeId);
      const overContainer = findContainer(overId);

      if (!activeContainer || !overContainer) return;

      // Move logic
      if (activeContainer === overContainer) {
          // Reorder within same container
          const items = activeContainer === 'hidden' ? palette.hidden : palette.categories[activeContainer];
          const oldIndex = items.indexOf(activeId);
          const newIndex = items.indexOf(overId);

          if (oldIndex !== newIndex) {
              const newItems = arrayMove(items, oldIndex, newIndex);
              const newPalette = { ...palette };
              if (activeContainer === 'hidden') newPalette.hidden = newItems;
              else newPalette.categories[activeContainer] = newItems;
              
              handleSavePalette(newPalette);
          }
      } else {
          // Move between containers
          const sourceItems = activeContainer === 'hidden' ? palette.hidden : palette.categories[activeContainer];
          const destItems = overContainer === 'hidden' ? palette.hidden : palette.categories[overContainer];
          
          const oldIndex = sourceItems.indexOf(activeId);
          const newIndex = overId in palette.categories || overId === 'hidden' 
              ? destItems.length + 1 // Dropped on container placeholder
              : destItems.indexOf(overId);

          let newSource = [...sourceItems];
          newSource.splice(oldIndex, 1);
          
          let newDest = [...destItems];
          newDest.splice(newIndex >= 0 ? newIndex : newDest.length, 0, activeId);

          const newPalette = { ...palette };
          if (activeContainer === 'hidden') newPalette.hidden = newSource;
          else newPalette.categories[activeContainer] = newSource;
          
          if (overContainer === 'hidden') newPalette.hidden = newDest;
          else newPalette.categories[overContainer] = newDest;

          handleSavePalette(newPalette);
      }
  };

  // --- ACTIONS ---

  const handleGlobalAction = async (action) => {
    try {
      await setGlobalState(action);
    } catch (e) {
      alert(`Failed to set ${action}: ${e.message}`);
    }
  };

  const handleUpdateText = async () => {
    try {
      await updateGlobalText(inputText);
      alert("Global Status Updated!");
    } catch (e) {
      alert("Update Failed: " + e.message);
    }
  };

  const handleReloadText = async () => {
    try {
      const barsResp = await getBars();
      if (barsResp.data.global_content) {
         setInputText(barsResp.data.global_content);
      } else {
         alert("Master Bar is empty.");
      }
    } catch (e) {
      alert("Fetch Failed: " + e.message);
    }
  };

  const addEmojiToBar = (emoji) => {
    const str = emoji.string || `<:${emoji.name}:${emoji.id}>`; 
    setInputText(prev => prev + " " + str + " ");
  };

  const getEmojiObj = (name) => {
    return emojis.find(e => e.name === name);
  };

  // --- RENDERERS ---
  const renderCategory = (catName, items) => {
    return (
      <SortableContext 
        id={catName} 
        items={items} 
        strategy={rectSortingStrategy}
        key={catName}
      >
        <div className="mb-4">
            <h3 className="text-gray-400 font-bold uppercase text-xs tracking-wider mb-2 border-b border-gray-700 pb-1 flex justify-between">
                {catName}
                {items.length === 0 && <span className="text-[10px] text-gray-600">Drop Here</span>}
            </h3>
            <div className="flex flex-wrap gap-1 min-h-[3rem] transition-colors rounded" style={{ backgroundColor: items.length === 0 ? 'rgba(0,0,0,0.1)' : 'transparent' }}>
            {items.map(name => {
                const emo = getEmojiObj(name);
                if (!emo) return null; 
                return <SortableEmoji key={name} id={name} emoji={emo} onClick={addEmojiToBar} />;
            })}
            </div>
        </div>
      </SortableContext>
    );
  };

  return (
    <DndContext 
        sensors={sensors} 
        collisionDetection={closestCenter} 
        onDragStart={handleDragStart} 
        onDragEnd={handleDragEnd}
    >
    <div className="min-h-screen bg-[#1e2124] text-gray-100 font-sans p-6">
      <div className="max-w-6xl mx-auto space-y-6">
        
        {/* HEADER */}
        <header className="flex justify-between items-center bg-[#282b30] p-4 rounded-lg shadow-lg border-l-4 border-[#7289da]">
          <div>
            <h1 className="text-2xl font-bold text-white tracking-tight">NyxOS Control Center</h1>
            <div className="flex items-center gap-2 mt-1">
              <span className={`w-3 h-3 rounded-full ${status.status === 'online' ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.6)]' : 'bg-red-500'}`}></span>
              <span className="font-mono text-sm text-gray-300">
                {status.status === 'online' ? `Online (${status.latency}ms)` : 'OFFLINE'}
              </span>
              {status.user && <span className="text-xs bg-[#7289da] px-2 py-0.5 rounded text-white font-bold ml-2">{status.user}</span>}
            </div>
          </div>
          
          <div className="flex gap-2">
            <button 
              onClick={handleSync} 
              disabled={isSyncing}
              className={`flex items-center gap-2 px-4 py-2 bg-[#36393e] hover:bg-[#424549] rounded transition-all text-sm font-semibold border border-gray-700 ${isSyncing ? 'opacity-50' : ''}`}
            >
              <RefreshCw size={16} className={isSyncing ? 'animate-spin' : ''} />
              Sync Emojis
            </button>
          </div>
        </header>

        {/* MAIN GRID */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          
          {/* LEFT COLUMN: Controls & Editor */}
          <div className="lg:col-span-2 space-y-6">
            
            {/* Global Controls */}
            <div className="bg-[#282b30] p-5 rounded-lg shadow-md">
              <h2 className="text-lg font-bold mb-4 flex items-center gap-2">
                <Zap size={20} className="text-yellow-500" /> Global Actions
              </h2>
              <div className="grid grid-cols-3 gap-3">
                <button onClick={() => handleGlobalAction('awake')} className="flex flex-col items-center justify-center p-3 bg-[#36393e] hover:bg-green-900/30 hover:border-green-500 border border-transparent rounded transition-all group">
                  <Eye size={24} className="text-green-500 mb-1 group-hover:scale-110 transition-transform" />
                  <span className="font-bold text-sm">Awake All</span>
                  <span className="text-xs text-gray-500">Speed 0</span>
                </button>
                <button onClick={() => handleGlobalAction('idle')} className="flex flex-col items-center justify-center p-3 bg-[#36393e] hover:bg-yellow-900/30 hover:border-yellow-500 border border-transparent rounded transition-all group">
                  <EyeOff size={24} className="text-yellow-500 mb-1 group-hover:scale-110 transition-transform" />
                  <span className="font-bold text-sm">Idle All</span>
                  <span className="text-xs text-gray-500">Not Watching</span>
                </button>
                <button onClick={() => handleGlobalAction('sleep')} className="flex flex-col items-center justify-center p-3 bg-[#36393e] hover:bg-blue-900/30 hover:border-blue-500 border border-transparent rounded transition-all group">
                  <Power size={24} className="text-blue-500 mb-1 group-hover:scale-110 transition-transform" />
                  <span className="font-bold text-sm">Sleep All</span>
                  <span className="text-xs text-gray-500">Zzz Mode</span>
                </button>
              </div>
            </div>

            {/* Editor */}
            <div className="bg-[#282b30] p-5 rounded-lg shadow-md">
              <h2 className="text-lg font-bold mb-4 flex items-center gap-2">
                <Save size={20} className="text-blue-400" /> Master Bar Editor
              </h2>
              
              <div className="relative mb-4">
                <input 
                  type="text" 
                  value={inputText}
                  onChange={(e) => setInputText(e.target.value)}
                  placeholder="Enter status text... Click emojis to insert."
                  className="w-full bg-[#1e2124] border border-gray-700 rounded p-4 text-lg font-mono text-white focus:outline-none focus:border-[#7289da] focus:ring-1 focus:ring-[#7289da] transition-all pr-20"
                />
                <div className="absolute right-2 top-1/2 -translate-y-1/2 flex gap-1">
                  <button 
                    onClick={handleReloadText}
                    className="text-gray-500 hover:text-green-400 p-2 rounded hover:bg-gray-800 transition-colors"
                    title="Reload from Live"
                  >
                    <RefreshCw size={16} />
                  </button>
                  {inputText && (
                    <button 
                      onClick={() => setInputText("")}
                      className="text-gray-500 hover:text-red-400 p-2 rounded hover:bg-gray-800 transition-colors"
                      title="Clear"
                    >
                      <Trash2 size={16} />
                    </button>
                  )}
                </div>
              </div>

              {/* Preview Area */}
              <div className="bg-[#1e2124] rounded p-3 mb-4 min-h-[3rem] flex items-center flex-wrap gap-1 border border-gray-800">
                 <span className="text-xs text-gray-500 font-mono mr-2 select-none uppercase tracking-wider">Preview:</span>
                 {(() => {
                    // Simple parser: Split by emoji regex <a:name:id> or <:name:id>
                    const parts = inputText.split(/(<(?:a)?:[a-zA-Z0-9_]+:[0-9]+>)/g);
                    return parts.map((part, i) => {
                       const match = part.match(/<(?:a)?:([a-zA-Z0-9_]+):[0-9]+>/);
                       if (match) {
                           const name = match[1];
                           const emo = getEmojiObj(name);
                           if (emo) {
                               return <img key={i} src={emo.url} alt={name} className="w-6 h-6 object-contain inline-block mx-0.5" />;
                           }
                           // Fallback if emoji not found in our list but is a valid discord string
                           const idMatch = part.match(/:([0-9]+)>/);
                           if (idMatch) {
                                const ext = part.startsWith("<a:") ? "gif" : "png";
                                const url = `https://cdn.discordapp.com/emojis/${idMatch[1]}.${ext}`;
                                return <img key={i} src={url} alt={name} className="w-6 h-6 object-contain inline-block mx-0.5" />;
                           }
                       }
                       return <span key={i} className="text-gray-200">{part}</span>;
                    });
                 })()}
              </div>

              <div className="flex justify-between items-center">
                 <span className="text-xs text-gray-500 font-mono">
                    Use &lt;...&gt; for emojis. Simple text works too.
                 </span>
                 <button 
                   onClick={handleUpdateText}
                   className="bg-[#7289da] hover:bg-[#5b6eae] text-white px-6 py-2 rounded font-bold shadow-lg hover:shadow-xl transition-all active:scale-95"
                 >
                   Update Global Text
                 </button>
              </div>
            </div>

          </div>

          {/* RIGHT COLUMN: Palette */}
          <div className="bg-[#282b30] p-5 rounded-lg shadow-md flex flex-col h-[calc(100vh-8rem)]">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-lg font-bold">Emoji Palette</h2>
              <div className="flex bg-[#1e2124] rounded p-1">
                 <button 
                   onClick={() => setActiveTab('quick')}
                   className={`px-3 py-1 text-xs font-bold rounded ${activeTab === 'quick' ? 'bg-[#7289da] text-white' : 'text-gray-400 hover:text-white'}`}
                 >
                   Quick
                 </button>
                 <button 
                   onClick={() => setActiveTab('storage')}
                   className={`px-3 py-1 text-xs font-bold rounded ${activeTab === 'storage' ? 'bg-[#7289da] text-white' : 'text-gray-400 hover:text-white'}`}
                 >
                   Storage
                 </button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto pr-2 custom-scrollbar">
               {activeTab === 'quick' && palette.categories ? (
                 <>
                   {renderCategory("Yami", palette.categories.Yami || [])}
                   {renderCategory("Calyptra", palette.categories.Calyptra || [])}
                   {renderCategory("Riven", palette.categories.Riven || [])}
                   {renderCategory("SΛTVRN", palette.categories.SΛTVRN || [])}
                   {renderCategory("Other", palette.categories.Other || [])}
                 </>
               ) : (
                 <SortableContext 
                    id="hidden" 
                    items={palette.hidden || []}
                    strategy={rectSortingStrategy}
                 >
                    <div className="grid grid-cols-4 sm:grid-cols-5 gap-2 min-h-[50px] p-2 rounded" style={{backgroundColor: 'rgba(0,0,0,0.1)'}}>
                        {palette.hidden && palette.hidden.map(name => {
                            const emo = getEmojiObj(name);
                            if (!emo) return null;
                            return <SortableEmoji key={name} id={name} emoji={emo} onClick={addEmojiToBar} />;
                        })}
                        {(!palette.hidden || palette.hidden.length === 0) && (
                        <p className="col-span-full text-center text-gray-500 text-sm py-4">Storage is empty.</p>
                        )}
                    </div>
                 </SortableContext>
               )}
            </div>
          </div>

        </div>
      </div>
      
      {/* Drag Overlay for Visuals */}
      <DragOverlay>
        {activeDragId ? (
            <div className="w-12 h-12 p-2 bg-gray-700 rounded shadow-2xl opacity-90 scale-110 cursor-grabbing border border-[#7289da]">
                <img 
                    src={getEmojiObj(activeDragId)?.url} 
                    alt={activeDragId} 
                    className="w-full h-full object-contain" 
                />
            </div>
        ) : null}
      </DragOverlay>
    </div>
    </DndContext>
  );
}

export default App;