import React, { useState } from 'react';
import { Send, Trash2 } from 'lucide-react';
import { useDroppable } from '@dnd-kit/core';
import { SortableContext, horizontalListSortingStrategy } from '@dnd-kit/sortable';
import SortableEmoji from './SortableEmoji';
import { updateGlobalText } from '../api';

export default function BarEditor({ activeBarItems, emojiMap, onRemoveItem, onClear }) {
  const [status, setStatus] = useState("");
  
  // This area is now a Droppable Zone AND a Sortable Context
  const { setNodeRef, isOver } = useDroppable({
    id: 'active-bar-shelf',
  });

  const handleUpdate = async () => {
    setStatus("Sending...");
    
    // Convert the visual items back into a text string
    // items have a .emojiName property we can look up
    let textString = "";
    activeBarItems.forEach(item => {
        const emojiObj = emojiMap[item.emojiName];
        if (emojiObj) {
            textString += `${emojiObj.string} `;
        } else {
            // Fallback for text-only items if we add that later
            textString += `${item.emojiName} `;
        }
    });

    try {
      await updateGlobalText(textString.trim());
      setStatus("Updated!");
      setTimeout(() => setStatus(""), 2000);
    } catch (err) {
      setStatus("Error!");
      console.error(err);
    }
  };

  return (
    <div 
        className={`bg-discord-dark p-6 rounded-lg shadow-lg mb-6 border transition-colors ${isOver ? 'border-discord-green bg-discord-darker' : 'border-discord-darker'}`}
    >
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-discord-blurple font-bold text-lg uppercase tracking-wide">
            Master Bar Builder {isOver && <span className="text-green-400 text-sm ml-2">- Drop Here</span>}
        </h3>
        <button 
          onClick={onClear}
          className="text-gray-500 hover:text-red-400 text-sm flex items-center gap-1 transition-colors"
        >
          <Trash2 size={14} /> Clear All
        </button>
      </div>
      
      {/* The Visual Shelf */}
      <div 
        ref={setNodeRef}
        className="droppable-area bg-black/40 min-h-[120px] rounded-lg p-4 flex items-center flex-wrap gap-2 border-2 border-dashed border-gray-700 transition-colors"
        style={{ borderColor: isOver ? '#57F287' : '#2f3136', backgroundColor: isOver ? 'rgba(87, 242, 135, 0.1)' : '' }}
      >
        <SortableContext items={activeBarItems} strategy={horizontalListSortingStrategy}>
            {activeBarItems.map((item) => {
                const emojiObj = emojiMap[item.emojiName];
                // We pass the unique ID of the item instance, not the emoji name
                return (
                    <SortableEmoji 
                        key={item.id} 
                        id={item.id} 
                        emoji={emojiObj} 
                        onClick={() => onRemoveItem(item.id)} // Click on shelf to remove
                    />
                );
            })}
        </SortableContext>
        
        {activeBarItems.length === 0 && (
            <div className="w-full h-full flex items-center justify-center text-gray-600 italic select-none pointer-events-none">
                Drag emojis here from the palette below
            </div>
        )}
      </div>

      <div className="flex justify-between items-center mt-4">
        <span className={`text-sm font-bold ${status === 'Error!' ? 'text-red-500' : 'text-green-400'}`}>
          {status}
        </span>
        <button 
          onClick={handleUpdate}
          className="flex items-center gap-2 bg-discord-green hover:bg-green-500 text-white px-6 py-2 rounded font-bold transition-all active:scale-95 shadow-lg shadow-green-900/20"
        >
          <Send size={18} /> Update Globally
        </button>
      </div>
    </div>
  );
}
