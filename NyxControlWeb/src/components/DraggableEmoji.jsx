import React, { useState } from 'react';
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
  
  const [isHovered, setIsHovered] = useState(false);

  const style = {
    transform: CSS.Translate.toString(transform), // Translate is faster than Transform for pure drags
    opacity: isDragging ? 0.5 : 1,
    zIndex: isDragging ? 999 : 'auto',
  };

  const getEmojiUrl = (emoji) => {
      if (!emoji) return "";
      // If Discord emoji and animated
      if (emoji.source === 'discord' && emoji.animated && emoji.url.includes('.gif')) {
          // If NOT hovered, show static PNG
          if (!isHovered) {
              return emoji.url.replace('.gif', '.png');
          }
          // If hovered, return original GIF
          return emoji.url;
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
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      className="draggable-item w-12 h-12 p-1 m-1 bg-discord-dark hover:bg-gray-600 rounded cursor-pointer flex items-center justify-center border border-transparent hover:border-gray-500 transition-colors"
      title={emoji ? emoji.name : id}
    >
      {emoji ? (
        <img 
            src={getEmojiUrl(emoji)} 
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
