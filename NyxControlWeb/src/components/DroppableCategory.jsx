import React from 'react';
import { useDroppable } from '@dnd-kit/core';
import DraggableEmoji from './DraggableEmoji';

function DroppableCategory({ id, items, emojiMap, onEmojiClick }) {
  const { setNodeRef } = useDroppable({ id });

  return (
    <div className="droppable-area flex-1 min-w-[200px] bg-discord-dark/50 p-4 rounded-lg border border-white/5 flex flex-col">
      <h3 className="text-gray-400 font-bold mb-3 uppercase text-sm tracking-wider border-b border-white/10 pb-2">
        {id} <span className="text-xs font-normal text-gray-600 ml-2">({items.length})</span>
      </h3>
      
      <div 
        ref={setNodeRef} 
        className="flex flex-wrap content-start min-h-[100px] gap-1"
      >
        {items.map((emojiName) => {
            const emojiObj = emojiMap[emojiName];
            return (
              <DraggableEmoji 
                key={emojiName} 
                id={emojiName} 
                emoji={emojiObj} 
                onClick={onEmojiClick} 
              />
            );
        })}
        
        {items.length === 0 && (
          <div className="w-full h-20 flex items-center justify-center text-gray-700 text-sm italic border-2 border-dashed border-gray-800 rounded">
            Drop items here
          </div>
        )}
      </div>
    </div>
  );
}

export default React.memo(DroppableCategory);
