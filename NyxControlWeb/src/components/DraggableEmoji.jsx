import React from 'react';
import { useDraggable } from '@dnd-kit/core';
import { CSS } from '@dnd-kit/utilities';

function DraggableEmoji({ id, emoji, onClick }) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    isDragging
  } = useDraggable({ id });

  const style = {
    transform: CSS.Translate.toString(transform), // Translate is faster than Transform for pure drags
    opacity: isDragging ? 0.5 : 1,
    zIndex: isDragging ? 999 : 'auto',
  };

  const getStaticUrl = (emoji) => {
      if (!emoji) return "";
      if (emoji.source === 'discord' && emoji.animated && emoji.url.includes('.gif')) {
          return emoji.url.replace('.gif', '.png');
      }
      return emoji.url;
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      onClick={() => {
        if (!isDragging) onClick(emoji);
      }}
      className="draggable-item w-12 h-12 p-1 m-1 bg-discord-dark hover:bg-gray-600 rounded cursor-pointer flex items-center justify-center border border-transparent hover:border-gray-500 transition-colors"
      title={emoji ? emoji.name : id}
    >
      {emoji ? (
        <img 
            src={getStaticUrl(emoji)} 
            alt={emoji.name} 
            className="w-full h-full object-contain pointer-events-none" 
            loading="lazy"
        />
      ) : (
        <span className="text-xs text-gray-500 truncate">{id}</span>
      )}
    </div>
  );
}

export default React.memo(DraggableEmoji);
