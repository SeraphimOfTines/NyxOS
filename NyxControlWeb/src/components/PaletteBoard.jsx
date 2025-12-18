import React, { useState } from 'react';
import { DragOverlay } from '@dnd-kit/core';
import { ChevronDown, ChevronRight, Archive } from 'lucide-react';
import DroppableCategory from './DroppableCategory';
import DraggableEmoji from './DraggableEmoji';

export default function PaletteBoard({ items, emojiFullMap, onEmojiClick, activeId }) {
  // Default to closed to maximize performance
  const [isStorageOpen, setIsStorageOpen] = useState(false);

  return (
    <div className="flex flex-col gap-6 pb-4">
        {/* Main Categories Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
            {Object.keys(items).filter(k => k !== 'hidden').map(key => (
                <DroppableCategory 
                    key={key} 
                    id={key} 
                    items={items[key]} 
                    emojiMap={emojiFullMap} 
                    onEmojiClick={onEmojiClick}
                />
            ))}
        </div>

        {/* Storage / Hidden (Collapsible Bottom Panel) */}
        <div className="w-full border-t border-white/10 pt-4 mt-2">
             <button 
                onClick={() => setIsStorageOpen(!isStorageOpen)}
                className="flex items-center gap-2 text-gray-400 hover:text-white mb-2 transition-colors font-bold uppercase text-sm tracking-wider w-full text-left"
             >
                {isStorageOpen ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                <Archive size={16} />
                Storage / Hidden ({items.hidden.length})
             </button>

             {isStorageOpen && (
                 <div className="bg-black/20 rounded-lg p-1 animate-in fade-in slide-in-from-top-2 duration-200">
                     <DroppableCategory 
                        id="hidden" 
                        items={items.hidden} 
                        emojiMap={emojiFullMap} 
                        onEmojiClick={onEmojiClick}
                     />
                 </div>
             )}
        </div>

        <DragOverlay>
          {activeId ? (
            <DraggableEmoji 
                id={activeId} 
                emoji={emojiFullMap[activeId]} 
                onClick={() => {}} 
            />
          ) : null}
        </DragOverlay>
    </div>
  );
}
